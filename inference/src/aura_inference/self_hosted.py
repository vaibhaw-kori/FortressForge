"""Self-hosted GPU worker skeleton.

This module is the integration point where PyTorch + Diffusers will load
the actual AI model (Stable Video Diffusion img2vid, AnimateDiff +
IP-Adapter, Wan2.1-Animate, etc.). It is intentionally left as a TODO
in the foundation scaffold — the backend exercises this through the
same `VideoGenProvider` interface that `RunPodProvider` uses.
"""

from __future__ import annotations

from .base import VideoGenProvider
from .contracts import ProviderHandle, ProviderInput, ProviderResult


class SelfHostedProvider(VideoGenProvider):
    provider_id = "self-hosted"

    def __init__(self, model_name: str = "placeholder") -> None:
        self.model_name = model_name
        self._loaded = False

    def _ensure_loaded(self) -> None:
        # TODO: load torch model, attach IP-Adapter for identity preservation,
        # warm up pipeline, allocate CUDA buffers.
        raise NotImplementedError("Self-hosted model loading is out of scaffold scope")

    async def submit(self, payload: ProviderInput) -> ProviderHandle:
        raise NotImplementedError

    async def poll(self, handle: ProviderHandle) -> str:
        raise NotImplementedError

    async def result(self, handle: ProviderHandle) -> ProviderResult:
        raise NotImplementedError

    async def cancel(self, handle: ProviderHandle) -> None:
        raise NotImplementedError