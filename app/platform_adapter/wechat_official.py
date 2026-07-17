"""Small official WeChat MP API client with token caching.

The client is credential-agnostic: callers provide a short-lived app_id and
app_secret obtained from CredentialStore. Tokens never leave this module.
HTTP is injectable so all behavior is testable without a real account.
"""
from __future__ import annotations

import asyncio
from dataclasses import dataclass
from datetime import datetime, timedelta
from typing import Any

import httpx

from ..security import redact_text


class WechatMpApiError(RuntimeError):
    def __init__(self, code: str, message: str, *, retryable: bool = False):
        super().__init__(message)
        self.code = code
        self.retryable = retryable


@dataclass
class _Token:
    value: str
    expires_at: datetime


class WechatOfficialClient:
    BASE_URL = "https://api.weixin.qq.com"

    def __init__(self, *, http: httpx.AsyncClient | None = None,
                 timeout: float = 20.0):
        self.http = http or httpx.AsyncClient(timeout=timeout)
        self._owns_http = http is None
        self._tokens: dict[str, _Token] = {}
        self._locks: dict[str, asyncio.Lock] = {}

    async def close(self) -> None:
        if self._owns_http:
            await self.http.aclose()

    async def _json(self, method: str, path: str, **kwargs: Any) -> dict[str, Any]:
        response = await self.http.request(method, self.BASE_URL + path, **kwargs)
        try:
            data = response.json()
        except Exception as exc:
            raise WechatMpApiError("WECHAT_MP_INVALID_RESPONSE", "公众号接口返回不是 JSON") from exc
        if response.status_code == 429:
            raise WechatMpApiError("WECHAT_MP_API_RATE_LIMITED", "公众号接口限流", retryable=True)
        code = int(data.get("errcode") or 0)
        if code:
            retryable = code in (40001, 40014, 42001, 45009)
            mapped = "WECHAT_MP_TOKEN_INVALID" if code in (40001, 40014, 42001) else (
                "WECHAT_MP_API_RATE_LIMITED" if code == 45009 else "WECHAT_MP_API_ERROR"
            )
            raise WechatMpApiError(mapped, redact_text(str(data.get("errmsg") or code)), retryable=retryable)
        return data

    async def access_token(self, app_id: str, app_secret: str,
                           *, cache_key: str = "") -> str:
        if not app_id or not app_secret:
            raise WechatMpApiError("CREDENTIAL_REF_REQUIRED", "缺少公众号官方凭据")
        key = cache_key or app_id
        cached = self._tokens.get(key)
        if cached and cached.expires_at > datetime.utcnow() + timedelta(seconds=60):
            return cached.value
        lock = self._locks.setdefault(key, asyncio.Lock())
        async with lock:
            cached = self._tokens.get(key)
            if cached and cached.expires_at > datetime.utcnow() + timedelta(seconds=60):
                return cached.value
            data = await self._json("GET", "/cgi-bin/token", params={
                "grant_type": "client_credential", "appid": app_id, "secret": app_secret,
            })
            token = str(data.get("access_token") or "")
            if not token:
                raise WechatMpApiError("WECHAT_MP_TOKEN_REFRESH_FAILED", "公众号未返回 access token")
            self._tokens[key] = _Token(token, datetime.utcnow() + timedelta(
                seconds=max(60, int(data.get("expires_in") or 7200))))
            return token

    async def _with_token(self, method: str, path: str, *, app_id: str,
                          app_secret: str, cache_key: str, **kwargs: Any) -> dict[str, Any]:
        token = await self.access_token(app_id, app_secret, cache_key=cache_key)
        params = dict(kwargs.pop("params", {}) or {})
        params["access_token"] = token
        try:
            return await self._json(method, path, params=params, **kwargs)
        except WechatMpApiError as exc:
            if exc.code != "WECHAT_MP_TOKEN_INVALID":
                raise
            self._tokens.pop(cache_key, None)
            token = await self.access_token(app_id, app_secret, cache_key=cache_key)
            params["access_token"] = token
            return await self._json(method, path, params=params, **kwargs)

    async def check_account(self, app_id: str, app_secret: str, *, cache_key: str) -> dict[str, Any]:
        token = await self.access_token(app_id, app_secret, cache_key=cache_key)
        return {"ok": True, "platform": "wechat_mp", "app_id_suffix": app_id[-4:],
                "token_cached": bool(token), "capabilities": ["articles", "datacube", "draft", "publish"]}

    async def fetch_articles(self, app_id: str, app_secret: str, *, cache_key: str,
                             offset: int = 0, count: int = 20) -> list[dict[str, Any]]:
        data = await self._with_token("POST", "/cgi-bin/material/batchget_material",
                                      app_id=app_id, app_secret=app_secret,
                                      cache_key=cache_key,
                                      json={"type": "news", "offset": max(0, offset),
                                            "count": max(1, min(20, count))})
        rows: list[dict[str, Any]] = []
        for item in data.get("item") or []:
            media_id = str(item.get("media_id") or "")
            contents = item.get("content") or {}
            articles = contents.get("news_item") or contents.get("articles") or []
            for index, article in enumerate(articles):
                row = dict(article or {})
                row["media_id"] = media_id
                row["article_idx"] = index
                rows.append(row)
        return rows

    async def fetch_datacube(self, app_id: str, app_secret: str, *, cache_key: str,
                             begin_date: str, end_date: str) -> dict[str, Any]:
        summary = await self._with_token(
            "POST", "/datacube/getarticlesummary", app_id=app_id,
            app_secret=app_secret, cache_key=cache_key,
            json={"begin_date": begin_date, "end_date": end_date})
        users = await self._with_token(
            "POST", "/datacube/getusercumulate", app_id=app_id,
            app_secret=app_secret, cache_key=cache_key,
            json={"begin_date": begin_date, "end_date": end_date})
        return {"articles": summary.get("list") or [], "users": users.get("list") or []}

    async def create_draft(self, app_id: str, app_secret: str, *, cache_key: str,
                           article: dict[str, Any]) -> str:
        data = await self._with_token("POST", "/cgi-bin/draft/add", app_id=app_id,
                                      app_secret=app_secret, cache_key=cache_key,
                                      json={"articles": [article]})
        media_id = str(data.get("media_id") or "")
        if not media_id:
            raise WechatMpApiError("WECHAT_MP_ARTICLE_REJECTED", "公众号未返回草稿 media_id")
        return media_id

    async def submit_publish(self, app_id: str, app_secret: str, *, cache_key: str,
                             media_id: str) -> str:
        data = await self._with_token("POST", "/cgi-bin/freepublish/submit",
                                      app_id=app_id, app_secret=app_secret,
                                      cache_key=cache_key,
                                      json={"media_id": media_id})
        return str(data.get("publish_id") or "")
