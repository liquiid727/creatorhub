"""Xiaohongshu adapter facade.

The adapter keeps its offline normalization path dependency-light. Network clients
and signature dependencies are only imported when a real XHS API operation runs.
"""
from __future__ import annotations

from dataclasses import dataclass
from typing import Any, Iterable

from ..capabilities import get_capabilities
from ..contracts import ContentItem, PlatformCapabilities, PlatformId, TargetRef
from ..normalizers import normalize_aweme, normalize_comment


@dataclass(frozen=True)
class XiaohongshuAdapter:
    platform: PlatformId = PlatformId.XHS
    display_name: str = "小红书"
    capabilities: PlatformCapabilities = get_capabilities(PlatformId.XHS).capabilities

    def client_from_state(self, storage_state_json: str, user_agent: str,
                          timeout: float = 30.0, proxy: str = ""):
        """Build an XhsApiClient from Playwright storage_state, or return None."""
        from ...platforms.xhs.client import XhsApiClient, cookie_str_from_state, has_a1

        cookie_str = cookie_str_from_state(storage_state_json)
        if not has_a1(cookie_str):
            return None
        return XhsApiClient(cookie_str, user_agent, timeout=timeout, proxy=proxy)

    async def self_profile(self, storage_state_json: str, user_agent: str,
                           timeout: float = 30.0, proxy: str = "") -> tuple[dict, str]:
        """Return merged XHS self profile and normalized login error."""
        client = self.client_from_state(storage_state_json, user_agent, timeout, proxy)
        if client is None:
            return {}, "logged_out"
        try:
            me = await client.self_info()
        except Exception as exc:
            if exc.__class__.__name__ == "XhsApiError":
                return {}, "logged_out"
            return {}, "error"
        if not me or me.get("guest") is True or not me.get("user_id"):
            return {}, "logged_out"
        merged = dict(me)
        try:
            other = await client.user_info(me["user_id"])
            if other:
                merged = {**other, **me}
        except Exception:
            pass
        return merged, ""

    async def creator_profile(self, storage_state_json: str, proxy: str = "") -> dict | None:
        from ...platforms.xhs.publish import creator_profile

        return await creator_profile(storage_state_json, proxy=proxy)

    async def creator_check(self, storage_state_json: str, proxy: str = ""):
        from ...platforms.xhs.publish import creator_check

        return await creator_check(storage_state_json, proxy=proxy)

    def parse_self_user(self, data: dict) -> dict:
        from ...platforms.xhs.extract import parse_self_user

        return parse_self_user(data)

    def has_creator_cookies(self, storage_state_json: str) -> bool:
        from ...platforms.xhs.client import has_creator_cookies

        return has_creator_cookies(storage_state_json)

    async def account_user_id(self, storage_state_json: str, user_agent: str,
                              timeout: float = 30.0, proxy: str = "") -> str:
        client = self.client_from_state(storage_state_json, user_agent, timeout, proxy)
        if client is not None:
            try:
                me = await client.self_info()
                user_id = str((me or {}).get("user_id") or "")
                if user_id:
                    return user_id
            except Exception:
                pass
        prof = await self.creator_profile(storage_state_json, proxy=proxy)
        return (prof or {}).get("sec_uid") or ""

    async def note_card_from_state(self, storage_state_json: str, user_agent: str,
                                   timeout: float, proxy: str, note_id: str,
                                   xsec_token: str = "", xsec_source: str = "pc_note_detail") -> dict:
        client = self.client_from_state(storage_state_json, user_agent, timeout, proxy)
        if client is None:
            raise ValueError("登录态缺少 a1")
        try:
            return await client.note_detail(note_id, xsec_token=xsec_token, xsec_source=xsec_source)
        except Exception as exc:
            raise ValueError(f"取笔记失败:{exc}") from exc

    async def note_media_payload_from_state(self, storage_state_json: str, user_agent: str,
                                            timeout: float, proxy: str, note_id: str,
                                            xsec_token: str = "",
                                            xsec_source: str = "pc_note_detail") -> dict | None:
        card = await self.note_card_from_state(storage_state_json, user_agent, timeout, proxy,
                                               note_id, xsec_token, xsec_source)
        return self.note_media_payload(card or {}, note_id)

    async def note_comments_payload_from_state(self, storage_state_json: str, user_agent: str,
                                               timeout: float, proxy: str, note_id: str,
                                               xsec_token: str = "",
                                               xsec_source: str = "pc_note_detail") -> dict:
        client = self.client_from_state(storage_state_json, user_agent, timeout, proxy)
        if client is None:
            raise ValueError("登录态缺少 a1")
        token, source = xsec_token, xsec_source
        try:
            item = await client.note_detail_raw(note_id, xsec_token=xsec_token, xsec_source=xsec_source)
            fresh = item.get("xsec_token") or ((item.get("note_card") or {}).get("xsec_token"))
            if fresh:
                token, source = fresh, "pc_feed"
        except Exception:
            pass
        try:
            data = await client.note_comments(note_id, xsec_token=token, xsec_source=source)
        except Exception as exc:
            raise ValueError(f"取评论失败:{exc}") from exc
        comments = self.normalize_legacy_comments(data.get("comments") or [])
        comments.sort(key=lambda c: c.get("create_time") or 0, reverse=True)
        return {"comments": comments, "total": len(comments), "has_more": bool(data.get("has_more"))}

    async def post_comment(self, storage_state_json: str, user_agent: str, timeout: float,
                           proxy: str, note_id: str, content: str, xsec_token: str = "",
                           target_comment_id: str = "") -> tuple[bool, str, str]:
        client = self.client_from_state(storage_state_json, user_agent, timeout, proxy)
        if client is None:
            return False, "", "账号登录态缺少 a1,请重新扫码登录"
        try:
            data = await client.post_comment(note_id, content, xsec_token=xsec_token,
                                             target_comment_id=target_comment_id)
            comment_id = (data.get("comment") or {}).get("id") if isinstance(data, dict) else ""
            return True, (comment_id or "ok"), ""
        except Exception as exc:
            return False, "", repr(exc)

    async def publish(self, mgr: Any, identity: Any, storage_state_json: str,
                      media_type: str, title: str, desc: str, media_paths: list[str],
                      topics: str = "", headed: bool = True) -> tuple[bool, str, str]:
        from ...platforms.xhs.publish import publish_xhs

        return await publish_xhs(mgr, identity, storage_state_json, media_type, title,
                                 desc, media_paths, topics=topics, headed=headed)

    async def resolve_target(self, text: str, target_kind: str = "auto", user_agent: str = "") -> TargetRef:
        """Resolve a XHS note/user/keyword into TargetRef.

        `keyword` resolution is intentionally local and does not touch network.
        Note/user URL resolution delegates to the current prototype resolver.
        """
        value = (text or "").strip()
        if not value:
            raise ValueError("target input is empty")
        if target_kind == "keyword":
            return TargetRef(
                platform=self.platform,
                target_kind="keyword",
                platform_target_id=value,
                display_name="#" + value,
                source_url=value,
            )

        from ...platforms.xhs.resolve import looks_like_note, resolve_note, resolve_user

        if target_kind == "note" or (target_kind == "auto" and looks_like_note(value)):
            ref = await resolve_note(value, user_agent)
            if not ref:
                raise ValueError("无法解析小红书笔记")
            return TargetRef(
                platform=self.platform,
                target_kind="content",
                platform_target_id=ref.note_id,
                source_url=value,
                platform_extra={"xsec_token": ref.xsec_token, "xsec_source": ref.xsec_source},
            )

        ref = await resolve_user(value, user_agent)
        if not ref:
            raise ValueError("无法解析小红书创作者")
        return TargetRef(
            platform=self.platform,
            target_kind="creator",
            platform_target_id=ref.user_id,
            source_url=value,
            platform_extra={"xsec_token": ref.xsec_token, "xsec_source": ref.xsec_source},
        )

    def normalize_note_card(self, note_card: dict, brief: dict | None = None) -> ContentItem | None:
        aweme = _parse_note_detail(note_card, brief)
        if aweme is None:
            return None
        item = normalize_aweme(aweme, self.platform)
        if brief:
            extra = dict(item.platform_extra)
            if brief.get("xsec_token"):
                extra["xsec_token"] = brief.get("xsec_token")
            item.platform_extra = extra
        return item

    def normalize_briefs(self, raw_items: Iterable[dict]) -> list[dict]:
        return [b for b in (_parse_note_brief(item) for item in raw_items or []) if b]

    def normalize_comments(self, raw_comments: Iterable[dict], platform_content_id: str = "") -> list[dict]:
        parsed = self.normalize_legacy_comments(raw_comments)
        return [normalize_comment(c, self.platform, platform_content_id) for c in parsed]

    def normalize_legacy_comments(self, raw_comments: Iterable[dict]) -> list[dict]:
        """Return CreatorHub's existing comment dict shape for incremental migration."""
        return [c for c in (_parse_comment(raw) for raw in _flatten_comments(list(raw_comments or []))) if c]

    def published_from_read_items(self, raw_items: Iterable[dict], limit: int = 80) -> list[dict]:
        """Normalize notes captured from the www profile feed for the published list UI."""
        out: list[dict] = []
        for raw in list(raw_items or [])[:limit]:
            brief = _parse_note_brief(raw)
            if not brief:
                continue
            card = raw.get("note_card") or raw
            interact = card.get("interact_info") or {}
            out.append({
                "note_id": brief["note_id"],
                "title": brief.get("title") or "(无标题)",
                "type": brief.get("type") or "normal",
                "cover": brief.get("cover") or "",
                "images": [],
                "like": interact.get("liked_count") or 0,
                "time": card.get("time") or 0,
                "xsec_token": brief.get("xsec_token") or "",
                "xsec_source": "pc_feed",
            })
        return out

    def published_from_creator_notes(self, notes: Iterable[dict], limit: int = 80) -> list[dict]:
        """Normalize creator-center published notes for the published list UI."""
        out: list[dict] = []
        for note in list(notes or [])[:limit]:
            images = _creator_note_images(note)
            video_info = note.get("video_info") or {}
            cover = images[0] if images else (video_info.get("cover") if isinstance(video_info, dict) else "")
            out.append({
                "note_id": str(_first(note, "id", "noteId", "note_id", default="")),
                "title": _first(note, "display_title", "title", "desc", default="(无标题)"),
                "type": _first(note, "type", "noteType", default="normal"),
                "cover": cover or "",
                "images": images,
                "like": _first(note, "likes", "likeCount", default=0),
                "time": _first(note, "time", "postTime", default=0),
                "xsec_token": _first(note, "xsec_token", default=""),
                "xsec_source": _first(note, "xsec_source", default="pc_note_detail"),
            })
        return out

    def note_media_payload(self, note_card: dict, note_id: str) -> dict | None:
        """Return legacy media payload for preview endpoints."""
        item = self.normalize_note_card(note_card or {}, {"note_id": note_id})
        if not item:
            return None
        aweme = self.to_legacy_aweme(item)
        if not aweme.medias:
            return None
        return {
            "media_type": aweme.media_type,
            "desc": aweme.desc,
            "cover_url": aweme.cover or "",
            "medias": [
                {"url": m.url, "kind": m.kind, "ext": m.ext, "index": m.index}
                for m in aweme.medias
            ],
        }

    def to_legacy_aweme(self, item: ContentItem):
        """Bridge normalized ContentItem back to the downloader's Aweme-like shape."""
        media_type = "images" if item.content_type == "image_set" else item.content_type
        return _Obj(
            aweme_id=item.platform_content_id,
            desc=item.description or item.title,
            create_time=item.published_at or 0,
            author_name=item.platform_extra.get("author_name", ""),
            media_type=media_type or "unknown",
            medias=[
                _Obj(url=m.url, kind=m.kind, ext=m.ext, index=m.index)
                for m in item.media_assets
            ],
            cover=item.cover_url,
            quality_label=(item.media_assets[0].quality_label if item.media_assets else ""),
            like_count=item.metrics.likes,
            comment_count=item.metrics.comments,
            duration=int(item.platform_extra.get("duration") or 0),
            platform=self.platform.value,
        )

    async def fetch_creator_contents(
        self,
        *,
        cookie_str: str,
        user_agent: str,
        user_id: str,
        xsec_token: str = "",
        proxy: str = "",
        limit: int = 20,
    ) -> list[ContentItem]:
        """Fetch creator notes through the existing XhsApiClient and normalize them."""
        from ...platforms.xhs.client import XhsApiClient

        client = XhsApiClient(cookie_str, user_agent, proxy=proxy)
        data = await client.notes_by_creator(user_id, xsec_token=xsec_token, page_size=limit)
        return await self._hydrate_briefs(client, self.normalize_briefs(data.get("notes") or []), "pc_feed")

    async def search_contents(
        self,
        *,
        cookie_str: str,
        user_agent: str,
        keyword: str,
        proxy: str = "",
        limit: int = 20,
    ) -> list[ContentItem]:
        """Search XHS notes through the existing XhsApiClient and normalize them."""
        from ...platforms.xhs.client import XhsApiClient

        client = XhsApiClient(cookie_str, user_agent, proxy=proxy)
        briefs = self.normalize_briefs(await client.search_notes(keyword, page_size=limit))
        return await self._hydrate_briefs(client, briefs, "pc_search")

    async def _hydrate_briefs(self, client: Any, briefs: list[dict], xsec_source: str) -> list[ContentItem]:
        items: list[ContentItem] = []
        for brief in briefs:
            card = await client.note_detail(
                brief["note_id"],
                xsec_token=brief.get("xsec_token", ""),
                xsec_source=xsec_source,
            )
            item = self.normalize_note_card(card, brief)
            if item:
                items.append(item)
        return items


def _first(d: dict, *keys, default=None):
    for key in keys:
        value = (d or {}).get(key)
        if value not in (None, "", 0, []):
            return value
    return default


def _num(value: Any) -> int:
    if isinstance(value, (int, float)):
        return int(value)
    text = str(value or "").strip().replace("+", "")
    try:
        if "万" in text:
            return int(float(text.replace("万", "")) * 10000)
        if "亿" in text:
            return int(float(text.replace("亿", "")) * 100000000)
        return int(float(text))
    except (TypeError, ValueError):
        return 0


def _parse_note_brief(item: dict) -> dict | None:
    if not isinstance(item, dict):
        return None
    note_id = str(_first(item, "note_id", "id", default="") or "")
    xsec_token = str(item.get("xsec_token") or "")
    card = item.get("note_card") or item
    if not note_id:
        note_id = str(_first(card, "note_id", "id", default="") or "")
    if not note_id:
        return None
    cover = card.get("cover") or {}
    cover_url = _first(cover, "url_default", "url_pre", "url") or ""
    if not cover_url and isinstance(cover.get("info_list"), list) and cover["info_list"]:
        cover_url = cover["info_list"][0].get("url", "")
    return {
        "note_id": note_id,
        "xsec_token": xsec_token,
        "type": card.get("type") or "normal",
        "title": _first(card, "display_title", "title", "desc", default="") or "",
        "cover": cover_url,
    }


def _image_url(image: dict) -> str:
    for scene in ("WB_DFT", "WB_PRV"):
        for item in image.get("info_list") or []:
            if item.get("image_scene") == scene and item.get("url"):
                return item["url"]
    for item in image.get("info_list") or []:
        if item.get("url"):
            return item["url"]
    return _first(image, "url_default", "url_pre", "url", default="") or ""


def _video_url(note_card: dict) -> str:
    stream = (((note_card.get("video") or {}).get("media") or {}).get("stream") or {})
    for codec in ("h264", "h265", "av1", "h266"):
        for item in stream.get(codec) or []:
            url = item.get("master_url") or (item.get("backup_urls") or [""])[0]
            if url:
                return url
    consumer = (note_card.get("video") or {}).get("consumer") or {}
    key = consumer.get("origin_video_key") or consumer.get("originVideoKey")
    return f"https://sns-video-bd.xhscdn.com/{key}" if key else ""


def _parse_note_detail(note_card: dict, brief: dict | None = None):
    if not isinstance(note_card, dict):
        return None
    note_id = str(_first(note_card, "note_id", "id", default=(brief or {}).get("note_id", "")) or "")
    if not note_id:
        return None
    user = note_card.get("user") or {}
    title = _first(note_card, "title", "display_title", default="") or ""
    desc = (note_card.get("desc") or "").strip()
    full_desc = (title + ("\n" + desc if desc and desc != title else "")).strip() or (brief or {}).get("title", "")
    timestamp = int(_first(note_card, "time", "create_time", default=0) or 0)
    if timestamp > 10_000_000_000:
        timestamp //= 1000
    media_type = "video" if (note_card.get("type") or (brief or {}).get("type")) == "video" else "images"
    media_items = []
    cover = ""
    if media_type == "video":
        url = _video_url(note_card)
        if url:
            media_items.append(_Obj(url=url, kind="video", ext="mp4", index=0))
        images = note_card.get("image_list") or []
        if images:
            cover = _image_url(images[0])
    else:
        for index, image in enumerate(note_card.get("image_list") or []):
            url = _image_url(image)
            if url:
                media_items.append(_Obj(url=url, kind="image", ext="jpeg", index=index))
        if media_items:
            cover = media_items[0].url
    if not media_items:
        return None
    interact = note_card.get("interact_info") or {}
    return _Obj(
        aweme_id=note_id,
        desc=full_desc,
        create_time=timestamp,
        author_name=_first(user, "nickname", "nick_name", "name", default="") or "",
        media_type=media_type,
        medias=media_items,
        cover=cover or (brief or {}).get("cover", ""),
        quality_label="",
        like_count=_num(_first(interact, "liked_count", "likedCount", default=0)),
        comment_count=_num(_first(interact, "comment_count", "commentCount", default=0)),
        duration=0,
        platform=PlatformId.XHS.value,
    )


def _parse_comment(raw: dict) -> dict | None:
    comment_id = str(_first(raw, "id", "comment_id", default="") or "")
    if not comment_id:
        return None
    user = raw.get("user_info") or raw.get("user") or {}
    target = raw.get("target_comment") or {}
    timestamp = int(_first(raw, "create_time", "createTime", default=0) or 0)
    if timestamp > 10_000_000_000:
        timestamp //= 1000
    return {
        "comment_id": comment_id,
        "text": (_first(raw, "content", "text", default="") or "").strip(),
        "user_nickname": _first(user, "nickname", "nick_name", "name", default="") or "",
        "like_count": _num(_first(raw, "like_count", "liked_count", default=0)),
        "create_time": timestamp,
        "reply_to": str(_first(target, "id", "comment_id", default="") or ""),
    }


def _flatten_comments(raw_list: list) -> list:
    flattened = []
    for comment in raw_list or []:
        flattened.append(comment)
        flattened.extend(comment.get("sub_comments") or comment.get("subComments") or [])
    return flattened


def _creator_note_images(note: dict) -> list[str]:
    images: list[str] = []
    for item in note.get("images_list") or note.get("imageList") or []:
        if isinstance(item, dict):
            url = item.get("url") or item.get("url_default") or item.get("urlDefault") or ""
            if url:
                images.append(url)
    return images


class _Obj:
    def __init__(self, **kwargs: Any) -> None:
        self.__dict__.update(kwargs)
