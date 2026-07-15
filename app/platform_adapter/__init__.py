"""Platform adapter contract package.

This package is the first low-intrusion boundary around CreatorHub's existing
platform-specific functions. It defines explicit capabilities and normalized
models before moving platform branches out of the API and engine layers.
"""
from .capabilities import BUILTIN_CAPABILITIES, get_capabilities, list_capabilities
from .contracts import (
    AdapterCapability,
    AdapterHealth,
    ContentItem,
    ContentMetrics,
    MediaAsset,
    PlatformCapabilities,
    PlatformId,
    TargetRef,
)
from .registry import PlatformAdapter, PlatformRegistry, default_registry
from .runtime import (AdapterTaskRuntime, XhsCreatorBriefBatch, XhsMediaRefresh,
                      XhsScanBatch, XhsScanItem)

__all__ = [
    "AdapterCapability",
    "AdapterHealth",
    "AdapterTaskRuntime",
    "BUILTIN_CAPABILITIES",
    "ContentItem",
    "ContentMetrics",
    "MediaAsset",
    "PlatformAdapter",
    "PlatformCapabilities",
    "PlatformId",
    "PlatformRegistry",
    "TargetRef",
    "XhsCreatorBriefBatch",
    "XhsMediaRefresh",
    "XhsScanBatch",
    "XhsScanItem",
    "default_registry",
    "get_capabilities",
    "list_capabilities",
]
