"""Platform adapter contracts and normalized data models."""
from __future__ import annotations

from dataclasses import dataclass, field
from enum import Enum
from typing import Any, Dict, List, Optional


class PlatformId(str, Enum):
    """Platform ids used by the current CreatorHub prototype.

    Keep values aligned with existing database/API values to avoid a breaking
    migration. Production-facing aliases can be added at the API boundary later.
    """

    DOUYIN = "douyin"
    XHS = "xhs"
    KUAISHOU = "kuaishou"
    SHIPINHAO = "shipinhao"
    WECHAT_MP = "wechat_mp"


@dataclass(frozen=True)
class PlatformCapabilities:
    public_content_monitor: bool = False
    keyword_search: bool = False
    own_account_works: bool = False
    content_download: bool = False
    comment_read: bool = False
    comment_write: bool = False
    publish: bool = False
    follow_graph: bool = False
    dm: bool = False
    creator_center: bool = False
    requires_logged_account_for_read: bool = False
    supports_browser_runtime: bool = True
    supports_api_runtime: bool = False
    known_limits: List[str] = field(default_factory=list)

    def supports(self, capability: str) -> bool:
        if not hasattr(self, capability):
            return False
        return bool(getattr(self, capability))

    def to_dict(self) -> Dict[str, Any]:
        return {
            "public_content_monitor": self.public_content_monitor,
            "keyword_search": self.keyword_search,
            "own_account_works": self.own_account_works,
            "content_download": self.content_download,
            "comment_read": self.comment_read,
            "comment_write": self.comment_write,
            "publish": self.publish,
            "follow_graph": self.follow_graph,
            "dm": self.dm,
            "creator_center": self.creator_center,
            "requires_logged_account_for_read": self.requires_logged_account_for_read,
            "supports_browser_runtime": self.supports_browser_runtime,
            "supports_api_runtime": self.supports_api_runtime,
            "known_limits": list(self.known_limits),
        }


@dataclass(frozen=True)
class AdapterCapability:
    platform: PlatformId
    display_name: str
    capabilities: PlatformCapabilities
    adapter_version: str = "0.1.0"
    capability_modes: Dict[str, PlatformCapabilities] = field(default_factory=dict)

    def to_dict(self) -> Dict[str, Any]:
        data = {
            "platform": self.platform.value,
            "display_name": self.display_name,
            "adapter_version": self.adapter_version,
            "capabilities": self.capabilities.to_dict(),
        }
        if self.capability_modes:
            data["capability_modes"] = {
                mode: capabilities.to_dict()
                for mode, capabilities in self.capability_modes.items()
            }
        return data


@dataclass
class TargetRef:
    platform: PlatformId
    target_kind: str
    platform_target_id: str
    display_name: str = ""
    avatar_url: str = ""
    source_url: str = ""
    platform_extra: Dict[str, Any] = field(default_factory=dict)

    def to_dict(self) -> Dict[str, Any]:
        return {
            "platform": self.platform.value,
            "target_kind": self.target_kind,
            "platform_target_id": self.platform_target_id,
            "display_name": self.display_name,
            "avatar_url": self.avatar_url,
            "source_url": self.source_url,
            "platform_extra": dict(self.platform_extra),
        }


@dataclass
class ContentMetrics:
    views: int = 0
    likes: int = 0
    comments: int = 0
    shares: int = 0
    collects: int = 0
    plays: int = 0
    extra: Dict[str, Any] = field(default_factory=dict)

    def to_dict(self) -> Dict[str, Any]:
        data = {
            "views": self.views,
            "likes": self.likes,
            "comments": self.comments,
            "shares": self.shares,
            "collects": self.collects,
            "plays": self.plays,
        }
        if self.extra:
            data["extra"] = dict(self.extra)
        return data


@dataclass
class MediaAsset:
    kind: str
    url: str
    ext: str = ""
    index: int = 0
    quality_label: str = ""
    object_key: str = ""
    local_path: str = ""
    mime: str = ""
    download_status: str = "pending"
    platform_extra: Dict[str, Any] = field(default_factory=dict)

    def to_dict(self) -> Dict[str, Any]:
        return {
            "kind": self.kind,
            "url": self.url,
            "ext": self.ext,
            "index": self.index,
            "quality_label": self.quality_label,
            "object_key": self.object_key,
            "local_path": self.local_path,
            "mime": self.mime,
            "download_status": self.download_status,
            "platform_extra": dict(self.platform_extra),
        }


@dataclass
class ContentItem:
    platform: PlatformId
    platform_content_id: str
    content_type: str
    title: str = ""
    description: str = ""
    cover_url: str = ""
    published_at: Optional[int] = None
    metrics: ContentMetrics = field(default_factory=ContentMetrics)
    media_assets: List[MediaAsset] = field(default_factory=list)
    platform_extra: Dict[str, Any] = field(default_factory=dict)

    def to_dict(self) -> Dict[str, Any]:
        return {
            "platform": self.platform.value,
            "platform_content_id": self.platform_content_id,
            "content_type": self.content_type,
            "title": self.title,
            "description": self.description,
            "cover_url": self.cover_url,
            "published_at": self.published_at,
            "metrics": self.metrics.to_dict(),
            "media_assets": [m.to_dict() for m in self.media_assets],
            "platform_extra": dict(self.platform_extra),
        }


@dataclass(frozen=True)
class AdapterHealth:
    platform: PlatformId
    status: str = "unknown"
    credential_status: str = "unknown"
    runtime_status: str = "unknown"
    last_error_code: str = ""
    last_error_message: str = ""
    adapter_version: str = "0.1.0"

    def to_dict(self) -> Dict[str, Any]:
        return {
            "platform": self.platform.value,
            "status": self.status,
            "credential_status": self.credential_status,
            "runtime_status": self.runtime_status,
            "last_error_code": self.last_error_code,
            "last_error_message": self.last_error_message,
            "adapter_version": self.adapter_version,
        }
