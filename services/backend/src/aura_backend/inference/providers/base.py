"""VideoGenerationProvider — async contract for any inference backend.

A provider returns opaque "handles" for submitted jobs; the worker
queries `status` and `result` until the job reaches a terminal state.

Implementations:
- MockVideoGenerationProvider — deterministic, for tests + offline demo.
- RunPodVideoGenerationProvider — HTTP-only skeleton, real wiring later.

Providers MUST NOT raise arbitrary exceptions. They MUST translate any
internal failure into a ProviderError (or subclass) so the worker can
decide whether to retry, fail, or dead-letter.
"""

from __future__ import annotations

from abc import ABC, abstractmethod
from dataclasses import dataclass, field
from typing import Any

from ...domain.video_asset import VideoCodec


# ---- Inputs / outputs ----


@dataclass(frozen=True)
class ProviderInput:
    job_id: str
    session_id: str
    experience_id: str
    capture_ref: str  # object key for the captured frame
    prompt: str = ""
    negative_prompt: str | None = None
    duration_sec: float = 4.0
    fps: int = 12
    resolution: str = "720x1280"
    aspect_ratio: str = "9:16"
    model_params: dict[str, Any] = field(default_factory=dict)
    idempotency_key: str | None = None


@dataclass(frozen=True)
class ProviderHandle:
    provider_id: str
    provider_job_id: str


@dataclass(frozen=True)
class ProviderResult:
    """The success artifact returned by a provider.

    `url` is the canonical location of the rendered video. The worker is
    responsible for copying it into the durable object store and updating
    the GenerationJob's output_ref.
    """

    output_ref: str  # canonical location, may be a URL or a local path
    duration_sec: float
    codec: VideoCodec = VideoCodec.H264
    size_bytes: int | None = None
    width: int | None = None
    height: int | None = None
    fps: int | None = None
    checksum_sha256: str | None = None
    metadata: dict[str, Any] = field(default_factory=dict)


# ---- Status reported by provider ----
PROVIDER_STATUS_QUEUED = "queued"
PROVIDER_STATUS_RUNNING = "running"
PROVIDER_STATUS_SUCCEEDED = "succeeded"
PROVIDER_STATUS_FAILED = "failed"
PROVIDER_STATUS_CANCELLED = "cancelled"


# ---- Progress callback contract ----


@dataclass(frozen=True)
class ProgressEvent:
    """Forwarded from the provider to the worker.

    Providers emit progress callbacks (when supported) via the optional
    `on_progress` argument of `run`. The worker publishes these to the
    WS event hub; no binary data ever traverses this channel.
    """

    progress: float  # 0..1
    phase: str | None = None
    detail: str | None = None


# ---- Abstract provider ----


class VideoGenerationProvider(ABC):
    provider_id: str = "base"

    @abstractmethod
    async def submit(self, payload: ProviderInput) -> ProviderHandle: ...

    @abstractmethod
    async def status(self, handle: ProviderHandle) -> str:
        """Return one of PROVIDER_STATUS_*."""

    @abstractmethod
    async def result(self, handle: ProviderHandle) -> ProviderResult: ...

    @abstractmethod
    async def cancel(self, handle: ProviderHandle) -> None: ...

    async def healthcheck(self) -> bool:
        """Best-effort check that the provider is reachable.

        Mock returns True; real implementations should ping the upstream.
        """
        return True


# ---- Registry ----


class ProviderRegistry:
    def __init__(self) -> None:
        self._providers: dict[str, VideoGenerationProvider] = {}

    def register(self, provider: VideoGenerationProvider) -> None:
        self._providers[provider.provider_id] = provider

    def unregister(self, provider_id: str) -> None:
        self._providers.pop(provider_id, None)

    def get(self, provider_id: str) -> VideoGenerationProvider:
        if provider_id not in self._providers:
            raise KeyError(f"Unknown provider '{provider_id}'")
        return self._providers[provider_id]

    def list_ids(self) -> list[str]:
        return sorted(self._providers.keys())

    def has(self, provider_id: str) -> bool:
        return provider_id in self._providers


_registry = ProviderRegistry()


def get_provider_registry() -> ProviderRegistry:
    return _registry