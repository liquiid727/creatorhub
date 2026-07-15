"""Platform adapter registry.

The registry is intentionally small for the first step: it centralizes platform
capabilities without moving existing platform implementations yet. Concrete
adapters can incrementally implement methods behind this boundary.
"""
from __future__ import annotations

from dataclasses import dataclass
from typing import Dict, Iterable, Protocol

from .capabilities import BUILTIN_CAPABILITIES
from .contracts import AdapterCapability, PlatformCapabilities, PlatformId


def _concrete_adapters() -> list[PlatformAdapter]:
    """Return concrete adapters that are ready behind the contract boundary."""
    from .adapters import XiaohongshuAdapter

    return [XiaohongshuAdapter()]


class PlatformAdapter(Protocol):
    platform: PlatformId
    display_name: str
    capabilities: PlatformCapabilities


@dataclass(frozen=True)
class CapabilityOnlyAdapter:
    platform: PlatformId
    display_name: str
    capabilities: PlatformCapabilities


class PlatformRegistry:
    def __init__(self) -> None:
        self._adapters: Dict[PlatformId, PlatformAdapter] = {}

    def register(self, adapter: PlatformAdapter) -> None:
        self._adapters[adapter.platform] = adapter

    def get(self, platform: str | PlatformId) -> PlatformAdapter:
        pid = platform if isinstance(platform, PlatformId) else PlatformId(platform)
        return self._adapters[pid]

    def has(self, platform: str | PlatformId) -> bool:
        try:
            pid = platform if isinstance(platform, PlatformId) else PlatformId(platform)
        except ValueError:
            return False
        return pid in self._adapters

    def all(self) -> Iterable[PlatformAdapter]:
        return self._adapters.values()

    def capability_records(self) -> list[AdapterCapability]:
        return [
            AdapterCapability(
                platform=a.platform,
                display_name=a.display_name,
                capabilities=a.capabilities,
            )
            for a in self.all()
        ]

    def require_capability(self, platform: str | PlatformId, capability: str) -> None:
        adapter = self.get(platform)
        if not adapter.capabilities.supports(capability):
            raise UnsupportedPlatformCapability(adapter.platform.value, capability)


class UnsupportedPlatformCapability(ValueError):
    def __init__(self, platform: str, capability: str) -> None:
        self.platform = platform
        self.capability = capability
        super().__init__(f"{platform} does not support capability: {capability}")


def _build_default_registry() -> PlatformRegistry:
    registry = PlatformRegistry()
    concrete = {adapter.platform: adapter for adapter in _concrete_adapters()}
    for record in BUILTIN_CAPABILITIES.values():
        adapter = concrete.get(record.platform)
        if adapter is not None:
            registry.register(adapter)
            continue
        registry.register(
            CapabilityOnlyAdapter(
                platform=record.platform,
                display_name=record.display_name,
                capabilities=record.capabilities,
            )
        )
    return registry


default_registry = _build_default_registry()
