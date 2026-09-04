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
from .wan_provider import WanVideoGenerationProvider, register_wan_provider

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