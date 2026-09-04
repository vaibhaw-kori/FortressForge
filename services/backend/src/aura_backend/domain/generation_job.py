"""GenerationJob aggregate.

A GenerationJob owns the AI generation lifecycle for a single
Session+Experience pair. It does not know anything about providers,
queues, or storage; it only enforces the state machine and holds
domain references.
"""

from __future__ import annotations

import uuid
from dataclasses import dataclass, field
from datetime import datetime, timezone

from .enums import GenerationJobState, JobTransitionError, assert_generation_transition
from .video_asset import VideoAsset


def _utcnow() -> datetime:
    return datetime.now(timezone.utc)


@dataclass
class GenerationJob:
    id: str = field(default_factory=lambda: uuid.uuid4().hex)
    session_id: str = ""
    experience_id: str = ""
    provider_id: str = "fake"
    state: GenerationJobState = GenerationJobState.CREATED
    attempts: int = 0
    max_attempts: int = 2
    input_ref: str | None = None
    output: VideoAsset | None = None
    progress: float = 0.0
    error_code: str | None = None
    error_message: str | None = None
    provider_job_id: str | None = None
    idempotency_key: str | None = None
    timeout_ms: int = 300_000
    # Latency tracking (ms)
    queued_latency_ms: int | None = None
    processing_latency_ms: int | None = None
    generation_latency_ms: int | None = None
    post_processing_latency_ms: int | None = None
    encoding_latency_ms: int | None = None
    total_latency_ms: int | None = None
    created_at: datetime = field(default_factory=_utcnow)
    updated_at: datetime = field(default_factory=_utcnow)
    started_at: datetime | None = None
    finished_at: datetime | None = None
    # Per-phase enter timestamps used to compute latencies.
    queued_at: datetime | None = None
    processing_at: datetime | None = None
    generating_at: datetime | None = None
    post_processing_at: datetime | None = None
    encoding_at: datetime | None = None

    # ---- construction validation ----

    def __post_init__(self) -> None:
        if not self.session_id:
            raise ValueError("GenerationJob.session_id required")
        if not self.experience_id:
            raise ValueError("GenerationJob.experience_id required")
        if self.max_attempts < 1:
            raise ValueError("GenerationJob.max_attempts must be >= 1")
        if not (0.0 <= self.progress <= 1.0):
            raise ValueError("GenerationJob.progress must be in [0, 1]")

    # ---- FSM transitions ----

    def _transition(self, to: GenerationJobState) -> None:
        try:
            assert_generation_transition(self.state, to)
        except JobTransitionError:
            raise
        now = _utcnow()
        prev = self.state
        self.state = to
        created = self.created_at
        if created.tzinfo is None:
            # SQLite returns naive datetimes; treat as UTC.
            from datetime import timezone as _tz

            created = created.replace(tzinfo=_tz.utc)
        # Per-phase enter timestamp + latency from previous enter.
        if to == GenerationJobState.QUEUED and self.queued_at is None:
            self.queued_at = now
            self.queued_latency_ms = int((now - created).total_seconds() * 1000)
        if to == GenerationJobState.PROCESSING and self.processing_at is None:
            self.processing_at = now
            self.processing_latency_ms = int((now - created).total_seconds() * 1000)
        if to == GenerationJobState.GENERATING and self.generating_at is None:
            self.generating_at = now
            self.generation_latency_ms = int((now - created).total_seconds() * 1000)
        if to == GenerationJobState.POST_PROCESSING and self.post_processing_at is None:
            self.post_processing_at = now
            self.post_processing_latency_ms = int((now - created).total_seconds() * 1000)
        if to == GenerationJobState.ENCODING and self.encoding_at is None:
            self.encoding_at = now
            self.encoding_latency_ms = int((now - created).total_seconds() * 1000)
        if to == GenerationJobState.QUEUED and self.started_at is None:
            self.started_at = now
        if to in {
            GenerationJobState.COMPLETED,
            GenerationJobState.FAILED,
            GenerationJobState.CANCELLED,
            GenerationJobState.TIMEOUT,
        }:
            self.finished_at = now
            self.total_latency_ms = int((now - created).total_seconds() * 1000)
        self.updated_at = now
        _ = prev  # silence linters

    def enqueue(self) -> None:
        self._transition(GenerationJobState.QUEUED)

    def begin_processing(self) -> None:
        self._transition(GenerationJobState.PROCESSING)

    def begin_generating(self) -> None:
        self._transition(GenerationJobState.GENERATING)

    def begin_post_processing(self) -> None:
        self._transition(GenerationJobState.POST_PROCESSING)

    def begin_encoding(self) -> None:
        self._transition(GenerationJobState.ENCODING)

    def complete(self, output: VideoAsset) -> None:
        if output is None:
            raise ValueError("output VideoAsset required")
        self._transition(GenerationJobState.COMPLETED)
        self.output = output
        self.progress = 1.0

    def fail(self, code: str, message: str | None = None) -> None:
        if not code:
            raise ValueError("error code required")
        self._transition(GenerationJobState.FAILED)
        self.error_code = code
        self.error_message = message

    def cancel(self) -> None:
        self._transition(GenerationJobState.CANCELLED)

    def timeout(self) -> None:
        self._transition(GenerationJobState.TIMEOUT)
        self.error_code = "timeout"

    # ---- progress / attempts ----

    def update_progress(self, progress: float) -> None:
        if not (0.0 <= progress <= 1.0):
            raise ValueError("progress must be in [0, 1]")
        # Only meaningful while we're in a running phase.
        if self.state in {
            GenerationJobState.PROCESSING,
            GenerationJobState.GENERATING,
            GenerationJobState.POST_PROCESSING,
            GenerationJobState.ENCODING,
        }:
            self.progress = max(self.progress, progress)
            self.updated_at = _utcnow()

    def increment_attempts(self) -> None:
        self.attempts += 1
        if self.attempts > self.max_attempts:
            raise ValueError("max_attempts exceeded")

    def can_retry(self) -> bool:
        return (
            self.state == GenerationJobState.FAILED
            and self.attempts < self.max_attempts
        )

    def reset_for_retry(self) -> None:
        """Reset the job back to CREATED so the queue can pick it up again.

        Idempotent: bumps `attempts`, clears output + error fields, keeps
        identity (id, session_id, experience_id, provider_id, idempotency_key).
        """
        if self.state != GenerationJobState.FAILED:
            raise ValueError(
                f"reset_for_retry requires FAILED state (got {self.state.value})"
            )
        self.attempts += 1
        if self.attempts > self.max_attempts:
            raise ValueError("max_attempts exceeded")
        self.state = GenerationJobState.CREATED
        self.output = None
        self.error_code = None
        self.error_message = None
        self.provider_job_id = None
        self.progress = 0.0
        self.finished_at = None
        self.queued_at = None
        self.processing_at = None
        self.generating_at = None
        self.post_processing_at = None
        self.encoding_at = None
        self.queued_latency_ms = None
        self.processing_latency_ms = None
        self.generation_latency_ms = None
        self.post_processing_latency_ms = None
        self.encoding_latency_ms = None
        self.total_latency_ms = None
        self.updated_at = _utcnow()