"""Mock provider — deterministic behavior for tests and offline demos.

Configurable per-instance via `MockProviderScript`:
- `outcome`: 'success' | 'fail' | 'timeout' | 'cancel_self'
- `total_ms`: total wall-clock duration of the job
- `progress_steps`: list of progress fractions to emit
- `fail_after_ms`: when outcome == 'fail', fail after this delay
- `fail_code`/`fail_message`: structured failure
"""

from __future__ import annotations

import asyncio
import os
import time
import uuid
from dataclasses import dataclass, field
from typing import Callable

from ..domain.video_asset import VideoCodec
from ..errors import (
    ProviderError,
    ProviderTimeoutError,
)
from .providers.base import (
    PROVIDER_STATUS_CANCELLED,
    PROVIDER_STATUS_FAILED,
    PROVIDER_STATUS_QUEUED,
    PROVIDER_STATUS_RUNNING,
    PROVIDER_STATUS_SUCCEEDED,
    ProgressEvent,
    ProviderHandle,
    ProviderInput,
    ProviderResult,
    VideoGenerationProvider,
)


@dataclass
class _MockJob:
    handle: ProviderHandle
    payload: ProviderInput
    state: str = PROVIDER_STATUS_QUEUED
    progress: float = 0.0
    result: ProviderResult | None = None
    error_code: str | None = None
    error_message: str | None = None
    started_at: float = field(default_factory=time.time)
    cancelled: bool = False
    call_count: int = 0


# Per-instance state hook: lets tests mutate the outcome mid-flight
# (e.g., fail the first call, succeed the second).
OnCallHook = "Callable[[int], MockProviderScript]"  # string; resolved at runtime


@dataclass
class MockProviderScript:
    outcome: str = "success"  # 'success' | 'fail' | 'timeout' | 'cancel_self'
    total_ms: int = 1200
    progress_steps: tuple[float, ...] = (0.1, 0.3, 0.6, 0.9)
    fail_after_ms: int = 400
    fail_code: str = "mock_failure"
    fail_message: str = "Mock provider simulated failure"
    output_ref: str = "mock://generated/{job_id}.mp4"
    duration_sec: float = 4.0
    codec: VideoCodec = VideoCodec.H264


ProgressCallback = Callable[[ProgressEvent], None]
OnCallHook = Callable[[int], "MockProviderScript"]


class MockVideoGenerationProvider(VideoGenerationProvider):
    provider_id = "mock"

    def __init__(
        self,
        script: MockProviderScript | None = None,
        on_call: OnCallHook | None = None,
    ) -> None:
        self._jobs: dict[str, _MockJob] = {}
        self._lock = asyncio.Lock()
        env_outcome = os.getenv("AURA_MOCK_PROVIDER_OUTCOME")
        if env_outcome and script is None:
            script = MockProviderScript(outcome=env_outcome)
        self._script = script or MockProviderScript()
        self._on_call = on_call
        self._global_call_count = 0

    def set_script(self, script: MockProviderScript) -> None:
        self._script = script

    def set_on_call(self, on_call: OnCallHook | None) -> None:
        self._on_call = on_call

    def set_script(self, script: MockProviderScript) -> None:
        self._script = script

    async def submit(self, payload: ProviderInput) -> ProviderHandle:
        async with self._lock:
            handle = ProviderHandle(provider_id=self.provider_id, provider_job_id=uuid.uuid4().hex)
            self._jobs[handle.provider_job_id] = _MockJob(handle=handle, payload=payload)
            return handle

    async def status(self, handle: ProviderHandle) -> str:
        async with self._lock:
            job = self._jobs.get(handle.provider_job_id)
        return job.state if job else PROVIDER_STATUS_FAILED

    async def result(self, handle: ProviderHandle) -> ProviderResult:
        async with self._lock:
            job = self._jobs.get(handle.provider_job_id)
        if job is None:
            raise ProviderError("mock_no_such_job", f"No such mock job {handle.provider_job_id}")
        if job.state != PROVIDER_STATUS_SUCCEEDED or job.result is None:
            raise ProviderError(
                job.error_code or "mock_not_ready",
                job.error_message or "Mock job not ready",
            )
        return job.result

    async def cancel(self, handle: ProviderHandle) -> None:
        async with self._lock:
            job = self._jobs.get(handle.provider_job_id)
        if job is None:
            return
        job.cancelled = True
        if job.state not in (PROVIDER_STATUS_SUCCEEDED, PROVIDER_STATUS_FAILED):
            job.state = PROVIDER_STATUS_CANCELLED
            job.error_code = "cancelled"
            job.error_message = "Cancelled by operator"

    async def drive(
        self,
        handle: ProviderHandle,
        on_progress: ProgressCallback | None = None,
        cancel_check: Callable[[], bool] | None = None,
    ) -> None:
        """Drive a mock job to completion in real-time.

        Used by the worker to exercise the full state machine without
        waiting on a real provider. Idempotent: second call is a no-op.
        """
        async with self._lock:
            job = self._jobs.get(handle.provider_job_id)
            if job is None:
                return
            if job.state in (PROVIDER_STATUS_SUCCEEDED, PROVIDER_STATUS_FAILED, PROVIDER_STATUS_CANCELLED):
                return
            job.state = PROVIDER_STATUS_RUNNING

        script = self._script
        # Per-call script override (lets tests fail-then-succeed).
        if self._on_call is not None:
            async with self._lock:
                self._global_call_count += 1
                cc = self._global_call_count
            override = self._on_call(cc)
            if override is not None:
                script = override
        step_ms = max(50, script.total_ms // max(1, len(script.progress_steps)))

        # Emit progress steps until done.
        for frac in script.progress_steps:
            await asyncio.sleep(step_ms / 1000.0)
            if cancel_check and cancel_check():
                async with self._lock:
                    job.state = PROVIDER_STATUS_CANCELLED
                    job.error_code = "cancelled"
                    job.error_message = "Cancelled"
                return
            async with self._lock:
                job.progress = frac
            if on_progress:
                on_progress(ProgressEvent(progress=frac))

        # Apply outcome.
        if script.outcome == "fail":
            await asyncio.sleep(max(0, script.fail_after_ms - step_ms * len(script.progress_steps)) / 1000.0)
            if cancel_check and cancel_check():
                async with self._lock:
                    job.state = PROVIDER_STATUS_CANCELLED
                return
            async with self._lock:
                job.state = PROVIDER_STATUS_FAILED
                job.error_code = script.fail_code
                job.error_message = script.fail_message
            return
        if script.outcome == "timeout":
            await asyncio.sleep(max(0, script.fail_after_ms - step_ms * len(script.progress_steps)) / 1000.0)
            if cancel_check and cancel_check():
                async with self._lock:
                    job.state = PROVIDER_STATUS_CANCELLED
                return
            async with self._lock:
                job.state = PROVIDER_STATUS_FAILED
                job.error_code = "timeout"
                job.error_message = "Mock provider simulated timeout"
            return
        if script.outcome == "cancel_self":
            async with self._lock:
                job.state = PROVIDER_STATUS_CANCELLED
                job.error_code = "cancelled"
                job.error_message = "Provider self-cancelled"
            return

        # success
        async with self._lock:
            job.progress = 1.0
            job.state = PROVIDER_STATUS_SUCCEEDED
            job.result = ProviderResult(
                output_ref=script.output_ref.format(job_id=job.handle.provider_job_id),
                duration_sec=script.duration_sec,
                codec=script.codec,
                size_bytes=None,
                width=None,
                height=None,
                fps=job.payload.fps,
                checksum_sha256=None,
                metadata={"mock": True},
            )

    async def healthcheck(self) -> bool:
        return True
