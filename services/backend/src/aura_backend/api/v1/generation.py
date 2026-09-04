"""Generation job routes (API v1)."""

from __future__ import annotations

from fastapi import APIRouter, Depends, status
from sqlalchemy.orm import Session as OrmSession

from ...db import get_db
from ...security import require_kiosk_token
from ...services import GenerationJobService
from .schemas import (
    CreateGenerationJobRequest,
    GenerationJobResponse,
    VideoAssetDTO,
)

router = APIRouter(prefix="/generation/jobs", tags=["generation"])


def _service(db: OrmSession = Depends(get_db)) -> GenerationJobService:
    return GenerationJobService(db)


def _to_dto(job) -> GenerationJobResponse:
    out: VideoAssetDTO | None = None
    if job.output is not None:
        a = job.output
        out = VideoAssetDTO(
            key=a.key,
            url=a.url,
            duration_sec=a.duration_sec,
            codec=a.codec.value,
            size_bytes=a.size_bytes,
            width=a.width,
            height=a.height,
            fps=a.fps,
            checksum_sha256=a.checksum_sha256,
        )
    return GenerationJobResponse(
        id=job.id,
        session_id=job.session_id,
        experience_id=job.experience_id,
        provider_id=job.provider_id,
        state=job.state,
        attempts=job.attempts,
        max_attempts=job.max_attempts,
        progress=job.progress,
        input_ref=job.input_ref,
        output=out,
        error_code=job.error_code,
        error_message=job.error_message,
        provider_job_id=job.provider_job_id,
        idempotency_key=job.idempotency_key,
        timeout_ms=job.timeout_ms,
        queued_latency_ms=job.queued_latency_ms,
        processing_latency_ms=job.processing_latency_ms,
        generation_latency_ms=job.generation_latency_ms,
        post_processing_latency_ms=job.post_processing_latency_ms,
        encoding_latency_ms=job.encoding_latency_ms,
        total_latency_ms=job.total_latency_ms,
        queued_at=job.queued_at,
        processing_at=job.processing_at,
        generating_at=job.generating_at,
        post_processing_at=job.post_processing_at,
        encoding_at=job.encoding_at,
        created_at=job.created_at,
        updated_at=job.updated_at,
        started_at=job.started_at,
        finished_at=job.finished_at,
    )


@router.post(
    "",
    response_model=GenerationJobResponse,
    status_code=status.HTTP_201_CREATED,
    responses={
        status.HTTP_404_NOT_FOUND: {"description": "Session not found"},
        status.HTTP_409_CONFLICT: {"description": "Idempotency key conflict"},
        status.HTTP_422_UNPROCESSABLE_ENTITY: {"description": "Invalid job request"},
    },
)
async def create_generation_job(
    body: CreateGenerationJobRequest,
    svc: GenerationJobService = Depends(_service),
    _auth=Depends(require_kiosk_token),
) -> GenerationJobResponse:
    job = svc.create(
        session_id=body.session_id,
        experience_id=body.experience_id,
        provider_id=body.provider_id,
        idempotency_key=body.idempotency_key,
        timeout_ms=body.timeout_ms,
    )
    # Enqueue for async processing — non-blocking HTTP
    from ...inference.queue import get_queue

    try:
        await get_queue().put(job.id)
    except Exception:
        # Queue failure should not fail the HTTP request; job remains QUEUED and can be retried
        pass
    return _to_dto(job)


@router.get(
    "/{job_id}",
    response_model=GenerationJobResponse,
    responses={status.HTTP_404_NOT_FOUND: {"description": "Job not found"}},
)
async def get_generation_job(
    job_id: str,
    svc: GenerationJobService = Depends(_service),
    _auth=Depends(require_kiosk_token),
) -> GenerationJobResponse:
    job = svc.get(job_id)
    return _to_dto(job)


@router.get("", response_model=list[GenerationJobResponse])
async def list_generation_jobs(
    session_id: str | None = None,
    svc: GenerationJobService = Depends(_service),
    _auth=Depends(require_kiosk_token),
) -> list[GenerationJobResponse]:
    jobs = svc.list_by_session(session_id) if session_id else svc.list()
    return [_to_dto(j) for j in jobs]


@router.post(
    "/{job_id}/cancel",
    response_model=GenerationJobResponse,
    responses={
        status.HTTP_404_NOT_FOUND: {"description": "Job not found"},
        status.HTTP_409_CONFLICT: {"description": "Job already terminal"},
    },
)
async def cancel_generation_job(
    job_id: str,
    svc: GenerationJobService = Depends(_service),
    _auth=Depends(require_kiosk_token),
) -> GenerationJobResponse:
    return _to_dto(svc.cancel(job_id))


@router.post(
    "/{job_id}/retry",
    response_model=GenerationJobResponse,
    responses={
        status.HTTP_404_NOT_FOUND: {"description": "Job not found"},
        status.HTTP_422_UNPROCESSABLE_ENTITY: {"description": "Job not retryable"},
    },
)
async def retry_generation_job(
    job_id: str,
    svc: GenerationJobService = Depends(_service),
    _auth=Depends(require_kiosk_token),
) -> GenerationJobResponse:
    job = svc.retry(job_id)
    from ...inference.queue import get_queue

    try:
        await get_queue().put(job.id)
    except Exception:
        pass
    return _to_dto(job)