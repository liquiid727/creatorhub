"""WeChat Official Account adapter contract slice.

The first slice is deliberately offline: it defines mode-aware capabilities and
normalization without accepting app secrets or depending on a live WeChat account.
"""
from __future__ import annotations

from dataclasses import dataclass
from enum import Enum
from typing import Any, Iterable
from urllib.parse import urlsplit

from ...security import redact_text
from ..capabilities import get_capabilities
from ..contracts import (
    ContentItem,
    ContentMetrics,
    MediaAsset,
    PlatformCapabilities,
    PlatformId,
    TargetRef,
)


class WechatMpMode(str, Enum):
    RESTRICTED = "restricted"
    OFFICIAL = "official"


OFFICIAL_CAPABILITIES = PlatformCapabilities(
    public_content_monitor=False,
    keyword_search=False,
    own_account_works=True,
    content_download=True,
    comment_read=False,
    comment_write=False,
    publish=True,
    follow_graph=False,
    dm=False,
    creator_center=True,
    requires_logged_account_for_read=True,
    supports_browser_runtime=False,
    supports_api_runtime=True,
    known_limits=[
        "数据统计和发布能力取决于公众号认证状态与官方 API 权限",
        "发布必须经过 CredentialRef、幂等、审批和审计门禁",
    ],
)


@dataclass(frozen=True)
class WechatMpAdapter:
    platform: PlatformId = PlatformId.WECHAT_MP
    display_name: str = "微信公众号"
    capabilities: PlatformCapabilities = get_capabilities(PlatformId.WECHAT_MP).capabilities

    @property
    def capability_modes(self) -> dict[str, PlatformCapabilities]:
        return {
            WechatMpMode.RESTRICTED.value: self.capabilities,
            WechatMpMode.OFFICIAL.value: OFFICIAL_CAPABILITIES,
        }

    def capabilities_for_mode(self, mode: str | WechatMpMode) -> PlatformCapabilities:
        resolved = mode if isinstance(mode, WechatMpMode) else WechatMpMode(mode)
        return OFFICIAL_CAPABILITIES if resolved is WechatMpMode.OFFICIAL else self.capabilities

    async def resolve_target(
        self, text: str, target_kind: str = "account", user_agent: str = ""
    ) -> TargetRef:
        """Create an account reference without touching the network."""
        del user_agent
        value = (text or "").strip()
        if not value:
            raise ValueError("target input is empty")
        if target_kind not in ("auto", "account"):
            raise ValueError("公众号 adapter 第一阶段只支持 account target")
        lower_value = value.lower()
        is_http_url = lower_value.startswith(("http://", "https://"))
        is_scheme_relative = value.startswith("//")
        if is_http_url or is_scheme_relative:
            parsed = urlsplit(value if is_http_url else "https:" + value)
            if parsed.username or parsed.password:
                raise ValueError("公众号账号标识不得包含 URL 用户名或密码")
        safe_value = redact_text(value)
        if safe_value != value:
            raise ValueError("公众号账号标识不得包含 token、Cookie 或授权参数")
        return TargetRef(
            platform=self.platform,
            target_kind="account",
            platform_target_id=safe_value,
            display_name=safe_value,
            source_url=safe_value if is_http_url or is_scheme_relative else "",
        )

    def normalize_article(self, raw: dict) -> ContentItem | None:
        if not isinstance(raw, dict):
            return None
        article_id = _article_id(raw)
        if not article_id:
            return None
        title = redact_text(str(_first(raw, "title", "name", default="") or ""))
        description = redact_text(
            str(_first(raw, "digest", "description", "content", default="") or "")
        )
        cover_url = redact_text(
            str(_first(raw, "thumb_url", "cover_url", "cover", default="") or "")
        )
        published_at = _timestamp(_first(raw, "publish_time", "update_time", "create_time", default=0))
        metrics = ContentMetrics(
            views=_number(_first(raw, "read_count", "int_page_read_count", default=0)),
            shares=_number(_first(raw, "share_count", default=0)),
            collects=_number(_first(raw, "favorite_count", "collect_count", default=0)),
            comments=_number(_first(raw, "comment_count", default=0)),
        )
        assets = [MediaAsset(kind="cover", url=cover_url, index=0)] if cover_url else []
        return ContentItem(
            platform=self.platform,
            platform_content_id=article_id,
            content_type="article",
            title=title,
            description=description,
            cover_url=cover_url,
            published_at=published_at or None,
            metrics=metrics,
            media_assets=assets,
            platform_extra={
                "author_name": redact_text(
                    str(_first(raw, "author", "author_name", default="") or "")
                ),
                "source_url": redact_text(
                    str(_first(raw, "url", "content_url", default="") or "")
                ),
            },
        )

    def normalize_articles(self, rows: Iterable[dict]) -> list[ContentItem]:
        return [item for item in (self.normalize_article(row) for row in rows or []) if item]

    def normalize_account_metrics(self, raw: dict, metric_date: str) -> dict[str, Any]:
        """Normalize official datacube-style counters without retaining credentials."""
        data = raw if isinstance(raw, dict) else {}
        return {
            "platform": self.platform.value,
            "metric_date": metric_date,
            "read_count": _number(_first(data, "read_count", "int_page_read_count", default=0)),
            "share_count": _number(_first(data, "share_count", default=0)),
            "favorite_count": _number(_first(data, "favorite_count", default=0)),
            "new_user": _number(_first(data, "new_user", default=0)),
            "cancel_user": _number(_first(data, "cancel_user", default=0)),
        }


def _first(data: dict, *keys: str, default: Any = None) -> Any:
    for key in keys:
        value = (data or {}).get(key)
        if value not in (None, "", []):
            return value
    return default


def _article_id(raw: dict) -> str:
    explicit = str(_first(raw, "article_id", "id", default="") or "")
    if explicit:
        return explicit
    group_id = str(_first(raw, "media_id", "msgid", default="") or "")
    if not group_id:
        return ""
    index = _first(raw, "article_idx", "idx", "index", default=None)
    return f"{group_id}:{index}" if index is not None else group_id


def _number(value: Any) -> int:
    try:
        text = str(value or 0).strip()
        number = int(text)
    except (TypeError, ValueError):
        try:
            number = int(float(value or 0))
        except (TypeError, ValueError, OverflowError):
            return 0
    if number < 0 or number > 9_223_372_036_854_775_807:
        return 0
    return number


def _timestamp(value: Any) -> int:
    number = _number(value)
    return number // 1000 if number > 10_000_000_000 else number
