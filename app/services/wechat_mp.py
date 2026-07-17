"""Official-account service built on RP-005 credentials and RP-004 tasks."""
from __future__ import annotations

import json
from datetime import datetime, timedelta
from typing import Any

from ..db import get_session
from ..models import AccountStatSnapshot, AccountWork, DouyinAccount, PlatformMetricSnapshot
from ..platform_adapter.adapters.wechat_mp import WechatMpAdapter
from ..platform_adapter.wechat_official import WechatMpApiError, WechatOfficialClient
from ..security import CredentialStore
from sqlmodel import select


class WechatMpService:
    def __init__(self, *, credentials: CredentialStore, client: WechatOfficialClient | None = None):
        self.credentials = credentials
        self.client = client or WechatOfficialClient()
        self.adapter = WechatMpAdapter()

    async def close(self) -> None:
        await self.client.close()

    def _account(self, account_id: int) -> DouyinAccount:
        with get_session() as session:
            account = session.get(DouyinAccount, account_id)
            if not account or account.platform != "wechat_mp":
                raise ValueError("WECHAT_MP_ACCOUNT_NOT_FOUND")
            return account

    def _credentials(self, account_id: int) -> tuple[DouyinAccount, dict[str, Any], str]:
        account = self._account(account_id)
        if account.account_mode != "official" or not account.credential_ref_id:
            raise ValueError("CREDENTIAL_REF_REQUIRED")
        secret = self.credentials.resolve(account.credential_ref_id, expected_kind="official_api")
        app_id = str(secret.get("app_id") or secret.get("appid") or "")
        app_secret = str(secret.get("app_secret") or secret.get("secret") or "")
        if not app_id or not app_secret:
            raise ValueError("CREDENTIAL_DECRYPT_FAILED")
        return account, {"app_id": app_id, "app_secret": app_secret}, account.credential_ref_id

    async def check_account(self, account_id: int) -> dict[str, Any]:
        account, secret, cache_key = self._credentials(account_id)
        result = await self.client.check_account(**secret, cache_key=cache_key)
        with get_session() as session:
            row = session.get(DouyinAccount, account_id)
            if row:
                row.status = "active"; session.add(row); session.commit()
        return {"account_id": account_id, **result}

    async def sync_articles(self, account_id: int, *, count: int = 20) -> dict[str, Any]:
        account, secret, cache_key = self._credentials(account_id)
        rows = await self.client.fetch_articles(**secret, cache_key=cache_key, count=count)
        added = 0; updated = 0
        with get_session() as session:
            for raw in rows:
                item = self.adapter.normalize_article(raw)
                if not item:
                    continue
                current = session.exec(
                    select(AccountWork).where(
                        AccountWork.platform == "wechat_mp",
                        AccountWork.account_id == account_id,
                        AccountWork.item_id == item.platform_content_id,
                    )
                ).first()
                values = dict(
                    platform="wechat_mp", account_id=account_id,
                    item_id=item.platform_content_id, desc=item.description,
                    media_type="article", cover_url=item.cover_url,
                    create_time=item.published_at or 0,
                    like_count=item.metrics.likes, comment_count=item.metrics.comments,
                    collect_count=item.metrics.collects, share_count=item.metrics.shares,
                    raw_json=json.dumps(raw, ensure_ascii=False), fetched_at=datetime.utcnow(),
                )
                if current:
                    for key, value in values.items(): setattr(current, key, value)
                    session.add(current); updated += 1
                else:
                    session.add(AccountWork(**values)); added += 1
            session.commit()
        return {"account_id": account_id, "fetched": len(rows), "added": added, "updated": updated}

    async def sync_metrics(self, account_id: int, *, begin_date: str, end_date: str) -> dict[str, Any]:
        account, secret, cache_key = self._credentials(account_id)
        data = await self.client.fetch_datacube(**secret, cache_key=cache_key,
                                                begin_date=begin_date, end_date=end_date)
        articles = data.get("articles") or []
        users = data.get("users") or []
        saved = 0
        with get_session() as session:
            for raw in users:
                metric_date = str(raw.get("ref_date") or raw.get("date") or begin_date)
                normalized = self.adapter.normalize_account_metrics(raw, metric_date)
                current = session.exec(select(AccountStatSnapshot).where(
                    AccountStatSnapshot.platform == "wechat_mp",
                    AccountStatSnapshot.account_id == account_id,
                    AccountStatSnapshot.date == metric_date,
                )).first()
                values = dict(platform="wechat_mp", account_id=account_id, date=metric_date,
                              follower_count=normalized["new_user"],
                              aweme_count=len(articles), total_like=normalized["read_count"],
                              total_comment=normalized["share_count"], total_play=normalized["favorite_count"])
                if current:
                    for key, value in values.items(): setattr(current, key, value)
                    session.add(current)
                else:
                    session.add(AccountStatSnapshot(**values))
                saved += 1
                metric = session.exec(select(PlatformMetricSnapshot).where(
                    PlatformMetricSnapshot.platform == "wechat_mp",
                    PlatformMetricSnapshot.account_id == account_id,
                    PlatformMetricSnapshot.content_id == "",
                    PlatformMetricSnapshot.metric_date == metric_date,
                )).first()
                metric_values = dict(platform="wechat_mp", account_id=account_id,
                                     content_id="", metric_date=metric_date,
                                     reads=normalized["read_count"],
                                     shares=normalized["share_count"],
                                     favorites=normalized["favorite_count"],
                                     new_users=normalized["new_user"],
                                     canceled_users=normalized["cancel_user"],
                                     raw_json=json.dumps(raw, ensure_ascii=False))
                if metric:
                    for key, value in metric_values.items(): setattr(metric, key, value)
                    session.add(metric)
                else:
                    session.add(PlatformMetricSnapshot(**metric_values))
            for raw in articles:
                metric_date = str(raw.get("ref_date") or raw.get("date") or begin_date)
                article = self.adapter.normalize_article(raw) or None
                content_id = article.platform_content_id if article else str(raw.get("article_id") or raw.get("msgid") or "")
                if not content_id:
                    continue
                metric = session.exec(select(PlatformMetricSnapshot).where(
                    PlatformMetricSnapshot.platform == "wechat_mp",
                    PlatformMetricSnapshot.account_id == account_id,
                    PlatformMetricSnapshot.content_id == content_id,
                    PlatformMetricSnapshot.metric_date == metric_date,
                )).first()
                values = dict(platform="wechat_mp", account_id=account_id,
                              content_id=content_id, metric_date=metric_date,
                              reads=int(raw.get("int_page_read_count") or raw.get("read_count") or 0),
                              likes=int(raw.get("like_count") or 0),
                              comments=int(raw.get("comment_count") or 0),
                              shares=int(raw.get("share_count") or 0),
                              favorites=int(raw.get("favorite_count") or 0),
                              raw_json=json.dumps(raw, ensure_ascii=False))
                if metric:
                    for key, value in values.items(): setattr(metric, key, value)
                    session.add(metric)
                else:
                    session.add(PlatformMetricSnapshot(**values))
                saved += 1
            session.commit()
        return {"account_id": account_id, "begin_date": begin_date,
                "end_date": end_date, "saved": saved}

    async def create_draft(self, account_id: int, article: dict[str, Any]) -> dict[str, Any]:
        _, secret, cache_key = self._credentials(account_id)
        media_id = await self.client.create_draft(**secret, cache_key=cache_key, article=article)
        return {"account_id": account_id, "media_id": media_id, "status": "draft"}

    async def publish_draft(self, account_id: int, media_id: str) -> dict[str, Any]:
        _, secret, cache_key = self._credentials(account_id)
        publish_id = await self.client.submit_publish(**secret, cache_key=cache_key, media_id=media_id)
        return {"account_id": account_id, "media_id": media_id,
                "publish_id": publish_id, "status": "submitted"}
