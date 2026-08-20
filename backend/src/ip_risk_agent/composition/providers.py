"""Source adapter registry and provider-owned router bundles."""

from __future__ import annotations

from dataclasses import dataclass

from fastapi import APIRouter
from iprisk_contracts import SourceAdapter, SourceType


class ProviderRegistryError(RuntimeError):
    pass


class SourceAdapterRegistry:
    def __init__(self, adapters: tuple[SourceAdapter, ...] = ()) -> None:
        self._adapters: dict[SourceType, SourceAdapter] = {}
        for adapter in adapters:
            self.register(adapter)

    def register(self, adapter: SourceAdapter) -> None:
        if adapter.source_type in self._adapters:
            raise ProviderRegistryError(
                f"duplicate source adapter: {adapter.source_type.value}"
            )
        self._adapters[adapter.source_type] = adapter

    def require(self, source_type: SourceType) -> SourceAdapter:
        adapter = self._adapters.get(source_type)
        if adapter is None:
            raise ProviderRegistryError(
                f"source adapter is not configured: {source_type.value}"
            )
        return adapter

    @property
    def source_types(self) -> tuple[SourceType, ...]:
        return tuple(sorted(self._adapters, key=lambda item: item.value))


@dataclass(frozen=True, slots=True)
class SourceRouterBundle:
    web: tuple[APIRouter, ...] = ()
    webhooks: tuple[APIRouter, ...] = ()
    desktop: tuple[APIRouter, ...] = ()

    @property
    def all(self) -> tuple[APIRouter, ...]:
        return self.web + self.webhooks + self.desktop


__all__ = [
    "ProviderRegistryError",
    "SourceAdapterRegistry",
    "SourceRouterBundle",
]
