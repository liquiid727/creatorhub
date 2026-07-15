"""Normalization helpers from prototype platform objects to adapter models."""
from __future__ import annotations

from typing import Any

from .contracts import ContentItem, ContentMetrics, MediaAsset, PlatformId


def normalize_aweme(aweme: Any, platform: str | PlatformId | None = None) -> ContentItem:
    """Convert CreatorHub's Aweme-like object to a platform-neutral ContentItem.

    This keeps the current parser output usable while preventing new layers from
    depending on fields such as aweme_id as a global name.
    """
    pid = _platform_id(platform or getattr(aweme, "platform", PlatformId.DOUYIN.value))
    media_type = getattr(aweme, "media_type", "") or "unknown"
    content_type = "image_set" if media_type == "images" else media_type or "unknown"
    metrics = ContentMetrics(
        likes=int(getattr(aweme, "like_count", 0) or 0),
        comments=int(getattr(aweme, "comment_count", 0) or 0),
        plays=int(getattr(aweme, "play_count", 0) or 0),
    )
    assets = [
        MediaAsset(
            kind=getattr(m, "kind", ""),
            url=getattr(m, "url", ""),
            ext=getattr(m, "ext", ""),
            index=int(getattr(m, "index", 0) or 0),
            quality_label=getattr(aweme, "quality_label", ""),
        )
        for m in list(getattr(aweme, "medias", []) or [])
    ]
    return ContentItem(
        platform=pid,
        platform_content_id=str(getattr(aweme, "aweme_id", "") or ""),
        content_type=content_type,
        title="",
        description=getattr(aweme, "desc", "") or "",
        cover_url=getattr(aweme, "cover", "") or "",
        published_at=int(getattr(aweme, "create_time", 0) or 0) or None,
        metrics=metrics,
        media_assets=assets,
        platform_extra={
            "author_name": getattr(aweme, "author_name", "") or "",
            "duration": int(getattr(aweme, "duration", 0) or 0),
            "legacy_content_id_field": "aweme_id",
        },
    )


def normalize_comment(raw: dict, platform: str | PlatformId, platform_content_id: str = "") -> dict:
    pid = _platform_id(platform)
    return {
        "platform": pid.value,
        "platform_content_id": platform_content_id or str(raw.get("aweme_id") or ""),
        "platform_comment_id": str(raw.get("comment_id") or ""),
        "parent_comment_id": str(raw.get("reply_to") or ""),
        "author_display_name": raw.get("user_nickname") or "",
        "text": raw.get("text") or "",
        "like_count": int(raw.get("like_count") or 0),
        "created_at_platform": int(raw.get("create_time") or 0),
        "platform_extra": {"legacy_comment_id_field": "comment_id"},
    }


def _platform_id(platform: str | PlatformId) -> PlatformId:
    if isinstance(platform, PlatformId):
        return platform
    return PlatformId(platform)
