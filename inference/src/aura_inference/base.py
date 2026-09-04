"""Provider base + registry."""

from __future__ import annotations

from abc import ABC, abstractmethod

from .contracts import ProviderHandle, ProviderInput, ProviderResult


class VideoGenProvider(ABC):
    provider_id: str = "base"

    @abstractmethod
    async def submit(self, payload: ProviderInput) -> ProviderHandle: ...

    @abstractmethod
    async def poll(self, handle: ProviderHandle) -> str: ...

    @abstractmethod
    async def result(self, handle: ProviderHandle) -> ProviderResult: ...

    @abstractmethod
    async def cancel(self, handle: ProviderHandle) -> None: ...


class ProviderRegistry:
    def __init__(self) -> None:
        self._providers: dict[str, VideoGenProvider] = {}

    def register(self, provider: VideoGenProvider) -> None:
        self._providers[provider.provider_id] = provider

    def get(self, provider_id: str) -> VideoGenProvider:
        if provider_id not in self._providers:
            raise KeyError(f"Unknown provider '{provider_id}'")
        return self._providers[provider_id]


registry = ProviderRegistry()