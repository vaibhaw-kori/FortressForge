"""SQLAlchemy ORM models for the prototype.

Tables: sessions, generation_jobs, video_assets, reel_items, experiences.

Designed to work against SQLite (prototype) and PostgreSQL (production)
without changes — only the connection URL differs.
"""

from __future__ import annotations

import enum
import uuid
from datetime import datetime, timezone
from typing import Any

from sqlalchemy import (
    JSON,
    DateTime,
    Enum,
    Float,
    ForeignKey,
    Integer,
    String,
    Text,
)
from sqlalchemy.orm import DeclarativeBase, Mapped, mapped_column


def _now() -> datetime:
    return datetime.now(timezone.utc)


class Base(DeclarativeBase):
    pass


class SessionStateDB(str, enum.Enum):
    IDLE = "IDLE"
    LANGUAGE_SELECTED = "LANGUAGE_SELECTED"
    THEME_SELECTED = "THEME_SELECTED"
    COUNTDOWN = "COUNTDOWN"
    CAPTURING = "CAPTURING"
    UPLOADED = "UPLOADED"
    GENERATING = "GENERATING"
    COMPLETED = "COMPLETED"
    ERROR = "ERROR"


class JobStateDB(str, enum.Enum):
    CREATED = "CREATED"
    QUEUED = "QUEUED"
    PROCESSING = "PROCESSING"
    GENERATING = "GENERATING"
    POST_PROCESSING = "POST_PROCESSING"
    ENCODING = "ENCODING"
    COMPLETED = "COMPLETED"
    FAILED = "FAILED"
    CANCELLED = "CANCELLED"
    TIMEOUT = "TIMEOUT"


class ReelKindDB(str, enum.Enum):
    CURATED = "curated"
    GENERATED = "generated"


class SessionRow(Base):
    __tablename__ = "sessions"

    id: Mapped[str] = mapped_column(String(64), primary_key=True, default=lambda: uuid.uuid4().hex)
    language: Mapped[str | None] = mapped_column(String(8), nullable=True)
    theme_id: Mapped[str | None] = mapped_column(String(64), nullable=True)
    state: Mapped[SessionStateDB] = mapped_column(
        Enum(SessionStateDB, native_enum=False),
        default=SessionStateDB.IDLE,
        nullable=False,
    )
    capture_ref: Mapped[str | None] = mapped_column(String(256), nullable=True)
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), default=_now)
    updated_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), default=_now, onupdate=_now
    )


class ExperienceRow(Base):
    """Persisted copy of the experience catalog.

    The catalog is also seeded in-memory at startup; the DB row is the
    source of truth for operator overrides in production.
    """

    __tablename__ = "experiences"

    id: Mapped[str] = mapped_column(String(64), primary_key=True)
    display_name: Mapped[str] = mapped_column(String(128), nullable=False)
    description: Mapped[str] = mapped_column(String(2048), nullable=False, default="")
    duration_sec: Mapped[float] = mapped_column(Float, nullable=False, default=4.0)
    fps: Mapped[int] = mapped_column(Integer, nullable=False, default=12)
    resolution: Mapped[str] = mapped_column(String(16), nullable=False, default="720x1280")
    aspect_ratio: Mapped[str] = mapped_column(String(8), nullable=False, default="9:16")
    thumbnail_url: Mapped[str | None] = mapped_column(String(512), nullable=True)
    enabled: Mapped[bool] = mapped_column(default=True, nullable=False)
    display_order: Mapped[int] = mapped_column(Integer, default=0, nullable=False)

    # Trusted AI-generation config.
    prompt: Mapped[str] = mapped_column(Text, nullable=False, default="")
    negative_prompt: Mapped[str | None] = mapped_column(Text, nullable=True)

    # Visual style.
    style_aesthetic: Mapped[str] = mapped_column(String(32), default="abstract", nullable=False)
    style_palette_name: Mapped[str] = mapped_column(String(64), default="default", nullable=False)
    style_keywords_json: Mapped[list[str]] = mapped_column(JSON, default=list)
    style_lighting: Mapped[str] = mapped_column(String(32), default="soft", nullable=False)
    style_texture: Mapped[str] = mapped_column(String(32), default="smooth", nullable=False)

    # Motion.
    motion_strength: Mapped[float] = mapped_column(Float, default=0.7, nullable=False)
    motion_camera_motion: Mapped[str] = mapped_column(String(32), default="static", nullable=False)
    motion_easing: Mapped[str] = mapped_column(String(32), default="ease_in_out", nullable=False)
    motion_intensity: Mapped[float] = mapped_column(Float, default=0.5, nullable=False)
    motion_loop: Mapped[bool] = mapped_column(default=False, nullable=False)

    # Model params (provider-agnostic).
    model_num_inference_steps: Mapped[int] = mapped_column(Integer, default=25, nullable=False)
    model_guidance_scale: Mapped[float] = mapped_column(Float, default=7.0, nullable=False)
    model_motion_bucket_id: Mapped[int] = mapped_column(Integer, default=127, nullable=False)
    model_seed_policy: Mapped[str] = mapped_column(String(32), default="random", nullable=False)
    model_fixed_seed: Mapped[int | None] = mapped_column(Integer, nullable=True)
    model_strength: Mapped[float] = mapped_column(Float, default=0.7, nullable=False)
    model_extra_json: Mapped[dict[str, Any]] = mapped_column(JSON, default=dict)

    # Visual theme (palette + bg music) for the kiosk UI.
    palette_json: Mapped[dict[str, Any]] = mapped_column(JSON, default=dict)
    background_music: Mapped[str | None] = mapped_column(String(256), nullable=True)
    metadata_json: Mapped[dict[str, Any]] = mapped_column(JSON, default=dict)

    # Localization.
    localized_names_json: Mapped[dict[str, Any]] = mapped_column(JSON, default=dict)
    localized_descriptions_json: Mapped[dict[str, Any]] = mapped_column(JSON, default=dict)
    supported_languages_json: Mapped[list[str]] = mapped_column(JSON, default=list)
    default_language: Mapped[str] = mapped_column(String(8), default="en", nullable=False)
    rtl_text: Mapped[bool] = mapped_column(default=False, nullable=False)


class GenerationJobRow(Base):
    __tablename__ = "generation_jobs"

    id: Mapped[str] = mapped_column(String(64), primary_key=True, default=lambda: uuid.uuid4().hex)
    session_id: Mapped[str] = mapped_column(
        String(64), ForeignKey("sessions.id"), nullable=False, index=True
    )
    experience_id: Mapped[str] = mapped_column(String(64), nullable=False, index=True)
    provider_id: Mapped[str] = mapped_column(String(64), nullable=False, default="fake")
    provider_job_id: Mapped[str | None] = mapped_column(String(128), nullable=True)
    state: Mapped[JobStateDB] = mapped_column(
        Enum(JobStateDB, native_enum=False),
        default=JobStateDB.CREATED,
        nullable=False,
        index=True,
    )
    attempts: Mapped[int] = mapped_column(Integer, default=0, nullable=False)
    max_attempts: Mapped[int] = mapped_column(Integer, default=2, nullable=False)
    input_ref: Mapped[str | None] = mapped_column(String(256), nullable=True)
    output_key: Mapped[str | None] = mapped_column(String(256), nullable=True)
    output_url: Mapped[str | None] = mapped_column(String(512), nullable=True)
    output_duration_sec: Mapped[float | None] = mapped_column(Float, nullable=True)
    output_codec: Mapped[str | None] = mapped_column(String(16), nullable=True)
    output_size_bytes: Mapped[int | None] = mapped_column(Integer, nullable=True)
    output_width: Mapped[int | None] = mapped_column(Integer, nullable=True)
    output_height: Mapped[int | None] = mapped_column(Integer, nullable=True)
    output_fps: Mapped[int | None] = mapped_column(Integer, nullable=True)
    output_checksum: Mapped[str | None] = mapped_column(String(64), nullable=True)
    progress: Mapped[float] = mapped_column(Float, default=0.0, nullable=False)
    error_code: Mapped[str | None] = mapped_column(String(64), nullable=True)
    error_message: Mapped[str | None] = mapped_column(Text, nullable=True)
    idempotency_key: Mapped[str | None] = mapped_column(
        String(128), nullable=True, unique=True
    )
    timeout_ms: Mapped[int] = mapped_column(Integer, default=300_000, nullable=False)
    queued_latency_ms: Mapped[int | None] = mapped_column(Integer, nullable=True)
    processing_latency_ms: Mapped[int | None] = mapped_column(Integer, nullable=True)
    generation_latency_ms: Mapped[int | None] = mapped_column(Integer, nullable=True)
    post_processing_latency_ms: Mapped[int | None] = mapped_column(Integer, nullable=True)
    encoding_latency_ms: Mapped[int | None] = mapped_column(Integer, nullable=True)
    total_latency_ms: Mapped[int | None] = mapped_column(Integer, nullable=True)
    queued_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True), nullable=True)
    processing_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True), nullable=True)
    generating_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True), nullable=True)
    post_processing_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True), nullable=True)
    encoding_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True), nullable=True)
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), default=_now)
    updated_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), default=_now, onupdate=_now
    )
    started_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True), nullable=True)
    finished_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True), nullable=True)


class VideoAssetRow(Base):
    """Reference row for a stored video artifact (curated or generated)."""

    __tablename__ = "video_assets"

    id: Mapped[str] = mapped_column(String(64), primary_key=True, default=lambda: uuid.uuid4().hex)
    key: Mapped[str] = mapped_column(String(256), nullable=False, unique=True)
    url: Mapped[str] = mapped_column(String(512), nullable=False)
    duration_sec: Mapped[float] = mapped_column(Float, nullable=False)
    codec: Mapped[str] = mapped_column(String(16), default="h264", nullable=False)
    size_bytes: Mapped[int | None] = mapped_column(Integer, nullable=True)
    width: Mapped[int | None] = mapped_column(Integer, nullable=True)
    height: Mapped[int | None] = mapped_column(Integer, nullable=True)
    fps: Mapped[int | None] = mapped_column(Integer, nullable=True)
    checksum_sha256: Mapped[str | None] = mapped_column(String(64), nullable=True)
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), default=_now)


class ReelItemRow(Base):
    __tablename__ = "reel_items"

    id: Mapped[str] = mapped_column(String(64), primary_key=True, default=lambda: uuid.uuid4().hex)
    kind: Mapped[ReelKindDB] = mapped_column(
        Enum(ReelKindDB, native_enum=False), default=ReelKindDB.CURATED, nullable=False
    )
    src: Mapped[str] = mapped_column(String(512), nullable=False)
    title: Mapped[str | None] = mapped_column(String(128), nullable=True)
    duration_sec: Mapped[float] = mapped_column(Float, default=4.0, nullable=False)
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), default=_now)