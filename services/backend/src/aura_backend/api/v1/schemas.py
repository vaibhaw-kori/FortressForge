"""DTOs (request/response schemas) for API v1."""

from __future__ import annotations

from datetime import datetime
from typing import Any

from pydantic import BaseModel, ConfigDict, Field

from ...domain.enums import GenerationJobState, ReelItemKind, SessionState


class _ORMModel(BaseModel):
    model_config = ConfigDict(from_attributes=True)


# ---- Sessions ----


class CreateSessionRequest(BaseModel):
    language: str | None = Field(default=None, max_length=8, description="BCP-47 / ISO code")


class SessionResponse(_ORMModel):
    id: str
    language: str | None
    theme_id: str | None
    state: SessionState
    capture_ref: str | None
    created_at: datetime
    updated_at: datetime


class SessionTransitionRequest(BaseModel):
    to: SessionState
    language: str | None = Field(default=None, max_length=8)
    theme_id: str | None = Field(default=None, max_length=64)


# ---- Experiences ----


class ExperienceThemeDTO(BaseModel):
    palette: dict[str, str] = Field(default_factory=dict)
    background_music: str | None = None


class MotionConfigDTO(BaseModel):
    strength: float = Field(default=0.7, ge=0.0, le=1.0)
    camera_motion: str = "static"
    easing: str = "ease_in_out"
    intensity: float = Field(default=0.5, ge=0.0, le=1.0)
    loop: bool = False


class ModelParamsDTO(BaseModel):
    """Provider-agnostic model parameters exposed for inspection.

    The frontend never sends these; the backend uses them when submitting
    work to the inference provider. Exposed here only so the operator
    console and theme picker can preview what each experience will do.
    """

    num_inference_steps: int = Field(default=25, ge=1, le=200)
    guidance_scale: float = Field(default=7.0, ge=0.0, le=30.0)
    motion_bucket_id: int = Field(default=127, ge=0, le=511)
    seed_policy: str = "random"
    fixed_seed: int | None = None
    strength: float = Field(default=0.7, ge=0.0, le=1.0)
    extra: dict[str, Any] = Field(default_factory=dict)


class VisualStyleDTO(BaseModel):
    aesthetic: str = "abstract"
    palette_name: str = "default"
    keywords: list[str] = Field(default_factory=list)
    lighting: str = "soft"
    texture: str = "smooth"


class LocalizedTextDTO(BaseModel):
    """Server-side rendered localized strings.

    `language` is the requested BCP-47 code; `fallback_language` is the
    language that was used to resolve the value when no exact match was
    found. The frontend uses these two fields to decide whether to show
    a "Translation missing" hint.
    """

    language: str
    value: str
    fallback_language: str = "en"
    rtl: bool = False


class ExperienceResponse(_ORMModel):
    id: str
    display_name: str
    description: str
    duration_sec: float = Field(gt=0, le=30)
    fps: int = Field(gt=0, le=60)
    resolution: str
    aspect_ratio: str
    thumbnail_url: str | None
    enabled: bool
    display_order: int

    # Trusted AI config (read-only here; never accepted from clients).
    prompt: str
    negative_prompt: str | None = None
    visual_style: VisualStyleDTO
    motion: MotionConfigDTO
    model_params: ModelParamsDTO

    # UI.
    theme: ExperienceThemeDTO
    metadata: dict[str, Any] = Field(default_factory=dict)

    # Localization.
    localized_names: LocalizedTextDTO | None = None
    localized_descriptions: LocalizedTextDTO | None = None
    supported_languages: list[str] = Field(default_factory=list)
    default_language: str = "en"
    rtl_text: bool = False


class ExperienceListResponse(BaseModel):
    items: list[ExperienceResponse]


class ExperienceListQuery(BaseModel):
    enabled_only: bool = Field(default=True)
    language: str | None = Field(default=None, max_length=8)


# ---- Generation jobs ----


class VideoAssetDTO(BaseModel):
    key: str
    url: str
    duration_sec: float = Field(gt=0)
    codec: str = "h264"
    size_bytes: int | None = None
    width: int | None = None
    height: int | None = None
    fps: int | None = None
    checksum_sha256: str | None = None


class GenerationJobResponse(_ORMModel):
    id: str
    session_id: str
    experience_id: str
    provider_id: str
    state: GenerationJobState
    attempts: int = Field(ge=0)
    max_attempts: int = Field(ge=1)
    progress: float = Field(ge=0.0, le=1.0)
    input_ref: str | None = None
    output: VideoAssetDTO | None = None
    error_code: str | None = None
    error_message: str | None = None
    provider_job_id: str | None = None
    idempotency_key: str | None = None
    timeout_ms: int = Field(default=300_000, ge=1000)
    queued_latency_ms: int | None = None
    processing_latency_ms: int | None = None
    generation_latency_ms: int | None = None
    post_processing_latency_ms: int | None = None
    encoding_latency_ms: int | None = None
    total_latency_ms: int | None = None
    queued_at: datetime | None = None
    processing_at: datetime | None = None
    generating_at: datetime | None = None
    post_processing_at: datetime | None = None
    encoding_at: datetime | None = None
    created_at: datetime
    updated_at: datetime
    started_at: datetime | None = None
    finished_at: datetime | None = None


class CreateGenerationJobRequest(BaseModel):
    session_id: str = Field(min_length=1, max_length=64)
    experience_id: str = Field(min_length=1, max_length=64)
    provider_id: str | None = Field(default=None, max_length=64)
    idempotency_key: str | None = Field(default=None, max_length=128)
    timeout_ms: int | None = Field(default=None, ge=1000, le=3600_000)


# ---- Reel (kept here so /api/v1/reel exists alongside) ----


class ReelItemDTO(BaseModel):
    id: str
    kind: ReelItemKind
    src: str
    title: str | None = None
    duration_sec: float = Field(gt=0)
    created_at: float | None = None