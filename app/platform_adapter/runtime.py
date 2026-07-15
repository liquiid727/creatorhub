"""Adapter task runtime helpers.

This module is the first execution boundary above concrete platform adapters. It
keeps the legacy engine state machine intact while moving platform-specific API
calls and normalization behind adapter-oriented methods.
"""
from __future__ import annotations

import asyncio
from dataclasses import dataclass, field
from typing import Any, Iterable

from .registry import PlatformRegistry, default_registry


@dataclass
class XhsScanItem:
    aweme: Any
    xsec_token: str = ""
    error: str = ""


@dataclass
class XhsScanBatch:
    items: list[XhsScanItem] = field(default_factory=list)
    author: dict | None = None
    raw_count: int = 0
    error: str = ""
    auth_error: bool = False


@dataclass
class XhsCreatorBriefBatch:
    briefs: list[dict] = field(default_factory=list)
    author: dict | None = None
    error: str = ""
    auth_error: bool = False


@dataclass
class XhsMediaRefresh:
    aweme: Any | None = None
    error: str = ""
    auth_error: bool = False


class AdapterTaskRuntime:
    """Runtime facade used by schedulers/engines to execute adapter tasks."""

    def __init__(self, registry: PlatformRegistry = default_registry,
                 user_agent: str = "", request_timeout: float = 20.0) -> None:
        self.registry = registry
        self.user_agent = user_agent
        self.request_timeout = request_timeout

    @property
    def xhs(self):
        return self.registry.get("xhs")

    def xhs_client_from_state(self, state: str, proxy: str = ""):
        return self.xhs.client_from_state(
            state, self.user_agent, timeout=self.request_timeout, proxy=proxy)

    async def xhs_creator_check(self, state: str, proxy: str = ""):
        return await self.xhs.creator_check(state, proxy=proxy)

    async def xhs_self_profile(self, state: str, proxy: str = "") -> tuple[dict, str]:
        return await self.xhs.self_profile(
            state, self.user_agent, timeout=self.request_timeout, proxy=proxy)

    def parse_xhs_self_user(self, data: dict) -> dict:
        return self.xhs.parse_self_user(data)

    async def scan_xhs_contents(
        self,
        *,
        state: str,
        proxy: str,
        kind: str,
        keyword: str,
        user_id: str,
        xsec_token: str,
        known_ids: Iterable[str],
        max_per_scan: int = 12,
        inter_item_delay: float = 0.6,
    ) -> XhsScanBatch:
        """Fetch and normalize XHS creator/keyword content for the legacy engine."""
        client = self.xhs_client_from_state(state, proxy)
        if not state or client is None:
            return XhsScanBatch(
                error="小红书监控需要绑定一个已登录的小红书账号(登录态缺少 a1,请重新扫码登录)",
                auth_error=True,
            )

        author = None
        raw_items: list[dict] = []
        error = ""
        try:
            if kind == "keyword":
                raw_items = await client.search_notes(keyword)
            else:
                data = await client.notes_by_creator(user_id, xsec_token=xsec_token)
                raw_items = data.get("notes") or []
                try:
                    author = await client.user_info(user_id)
                except Exception:
                    author = None
        except Exception as exc:
            error = f"小红书接口请求失败: {exc!r}"

        known = set(known_ids or [])
        seen: set[str] = set()
        items: list[XhsScanItem] = []
        for brief in self.xhs.normalize_briefs(raw_items):
            note_id = brief["note_id"]
            if note_id in seen or note_id in known:
                continue
            seen.add(note_id)
            if len(items) >= max_per_scan:
                break
            if len(seen) > 1 and inter_item_delay > 0:
                await asyncio.sleep(inter_item_delay)

            note_token = brief.get("xsec_token", "")
            detail_error = ""
            card = {}
            try:
                card = await client.note_detail(
                    note_id,
                    xsec_token=note_token,
                    xsec_source="pc_search" if kind == "keyword" else "pc_feed",
                )
            except Exception as exc:
                detail_error = str(exc)
            item = self.xhs.normalize_note_card(card or {}, brief) if card else None
            if item:
                aweme = self.xhs.to_legacy_aweme(item)
            else:
                aweme = self._fallback_xhs_aweme(note_id, brief)
            items.append(XhsScanItem(aweme=aweme, xsec_token=note_token, error=detail_error))

        return XhsScanBatch(items=items, author=author, raw_count=len(raw_items), error=error)

    async def xhs_fetch_comments(self, client: Any, note_id: str,
                                 xsec_token: str, known_ids: Iterable[str]) -> list[dict]:
        try:
            data = await client.note_comments(note_id, xsec_token=xsec_token)
            raw_comments = data.get("comments") or []
        except Exception:
            return []
        known = set(known_ids or [])
        return [
            c for c in self.xhs.normalize_legacy_comments(raw_comments)
            if c["comment_id"] not in known
        ]

    async def xhs_fetch_comments_from_state(self, state: str, proxy: str, note_id: str,
                                            xsec_token: str, known_ids: Iterable[str]) -> list[dict]:
        client = self.xhs_client_from_state(state, proxy)
        if client is None:
            return []
        return await self.xhs_fetch_comments(client, note_id, xsec_token, known_ids)

    async def xhs_creator_briefs(self, state: str, proxy: str, user_id: str,
                                 xsec_token: str, limit: int) -> XhsCreatorBriefBatch:
        client = self.xhs_client_from_state(state, proxy)
        if client is None:
            return XhsCreatorBriefBatch(error="账号登录态缺少 a1,请重新扫码登录", auth_error=True)
        try:
            data = await client.notes_by_creator(user_id, xsec_token=xsec_token)
            author = await client.user_info(user_id)
        except Exception as exc:
            return XhsCreatorBriefBatch(error=repr(exc))
        briefs = self.xhs.normalize_briefs(data.get("notes") or [])[:limit]
        return XhsCreatorBriefBatch(briefs=briefs, author=author)

    async def discover_xhs_comment_targets(
        self, *, state: str, proxy: str, mode: str, kind: str, keyword: str,
        target_user_id: str, target_note_id: str, target_xsec_token: str,
        account_user_id: str, account_nick: str, recent_works: int,
    ) -> tuple[list[dict], str]:
        client = self.xhs_client_from_state(state, proxy)
        if client is None:
            return [], "账号登录态缺少 a1,请重新扫码登录"

        candidates: list[dict] = []
        if mode == "auto_comment":
            if kind == "keyword":
                raw_items = await client.search_notes(keyword)
            else:
                data = await client.notes_by_creator(target_user_id, xsec_token=target_xsec_token)
                raw_items = data.get("notes") or []
            for brief in self.xhs.normalize_briefs(raw_items):
                candidates.append({
                    "aweme_id": brief["note_id"],
                    "xsec_token": brief.get("xsec_token", ""),
                    "target_comment_id": "",
                    "target_nick": "",
                    "ctx": {"kw": keyword},
                    "source_text": brief.get("title", ""),
                })
            return candidates, ""

        notes: list[dict] = []
        if kind == "work" and target_note_id:
            notes = [{"note_id": target_note_id, "xsec_token": target_xsec_token}]
        else:
            data = await client.notes_by_creator(account_user_id, xsec_token=target_xsec_token)
            notes = [
                {"note_id": b["note_id"], "xsec_token": b.get("xsec_token", "")}
                for b in self.xhs.normalize_briefs(data.get("notes") or [])[:recent_works]
            ]

        for note in notes:
            try:
                data = await client.note_comments(note["note_id"], xsec_token=note["xsec_token"])
            except Exception:
                continue
            for comment in self.xhs.normalize_legacy_comments(data.get("comments") or []):
                if not comment.get("comment_id"):
                    continue
                if comment.get("user_nickname") and comment["user_nickname"] == account_nick:
                    continue
                candidates.append({
                    "aweme_id": note["note_id"],
                    "xsec_token": note["xsec_token"],
                    "target_comment_id": comment["comment_id"],
                    "target_nick": comment.get("user_nickname", ""),
                    "ctx": {"nick": comment.get("user_nickname", "")},
                    "source_text": comment.get("text", ""),
                })
        return candidates, ""

    async def refresh_xhs_media(self, *, state: str, proxy: str, note_id: str,
                                xsec_token: str, kind: str) -> XhsMediaRefresh:
        client = self.xhs_client_from_state(state, proxy)
        if client is None:
            return XhsMediaRefresh(error="账号登录态缺少 a1,请重新扫码登录", auth_error=True)
        try:
            card = await client.note_detail(
                note_id, xsec_token=xsec_token,
                xsec_source="pc_search" if kind == "keyword" else "pc_feed")
        except Exception as exc:
            return XhsMediaRefresh(error=str(exc))
        item = self.xhs.normalize_note_card(card or {}, {"note_id": note_id}) if card else None
        aweme = self.xhs.to_legacy_aweme(item) if item else None
        if not aweme or not aweme.medias:
            return XhsMediaRefresh(error="重拉详情仍无媒体(笔记可能已删/私密)")
        return XhsMediaRefresh(aweme=aweme)

    async def publish_xhs(self, mgr: Any, identity: Any, state: str,
                          media_type: str, title: str, desc: str,
                          files: list[str], topics: str = "",
                          headed: bool = True) -> tuple[bool, str, str]:
        return await self.xhs.publish(
            mgr, identity, state, media_type, title, desc, files,
            topics=topics, headed=headed)

    async def post_xhs_comment(self, state: str, proxy: str, note_id: str,
                               content: str, xsec_token: str = "",
                               target_comment_id: str = "") -> tuple[bool, str, str]:
        return await self.xhs.post_comment(
            state, self.user_agent, self.request_timeout, proxy, note_id, content,
            xsec_token=xsec_token, target_comment_id=target_comment_id)

    @staticmethod
    def _fallback_xhs_aweme(note_id: str, brief: dict):
        from ..platforms.douyin.extract import Aweme

        aweme = Aweme(
            aweme_id=note_id,
            desc=brief.get("title", ""),
            create_time=0,
            author_name="",
            media_type="images",
        )
        aweme.platform = "xhs"
        aweme.cover = brief.get("cover", "")
        return aweme
