"""Inference layer (provider abstraction, queue, worker)."""

from .providers.base import (
    PROVIDER_STATUS_CANCELLED,
    PROVIDER_STATUS_FAILED,
    PROVIDER_STATUS_QUEUED,
    PROVIDER_STATUS_RUNNING,
    PROVIDER_STATUS_SUCCEEDED,
    ProgressEvent,
    ProviderHandle,
    ProviderInput,
    ProviderRegistry,
    ProviderResult,
    VideoGenerationProvider,
    get_provider_registry,
)
from .mock_provider import MockVideoGenerationProvider
from .runpod_provider import RunPodVideoGenerationProvider

try:  # Optional heavy deps (torch/diffusers) — only needed for wan-local
    from .wan_provider import WanVideoGenerationProvider, register_wan_provider
except ImportError:  # pragma: no cover - allows backend to run with mock provider
    WanVideoGenerationProvider = None  # type: ignore[assignment]

    def register_wan_provider(*args, **kwargs):  # type: ignore[no-redef]
        raise ImportError(
            "wan-local provider requires GPU extras: pip install -e '.[gpu]'"
        )

__all__ = [
    "PROVIDER_STATUS_CANCELLED",
    "PROVIDER_STATUS_FAILED",
    "PROVIDER_STATUS_QUEUED",
    "PROVIDER_STATUS_RUNNING",
    "PROVIDER_STATUS_SUCCEEDED",
    "MockVideoGenerationProvider",
    "ProgressEvent",
    "ProviderHandle",
    "ProviderInput",
    "ProviderRegistry",
    "ProviderResult",
    "RunPodVideoGenerationProvider",
    "VideoGenerationProvider",
    "WanVideoGenerationProvider",
    "get_provider_registry",
    "register_wan_provider",
]