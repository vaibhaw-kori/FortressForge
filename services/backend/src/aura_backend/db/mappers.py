"""Mappers: ORM row <-> domain object."""

from __future__ import annotations

from typing import Any

from ..domain import (
    Experience,
    ExperienceTheme,
    GenerationJob,
    GenerationJobState,
    LocalizedText,
    ModelParams,
    MotionConfig,
    ReelItem,
    ReelItemKind,
    Session,
    SessionState,
    VideoAsset,
    VideoCodec,
    VisualStyle,
)
from ..domain.video_asset import VideoCodec as _VideoCodec
from .models import (
    ExperienceRow,
    GenerationJobRow,
    JobStateDB,
    ReelItemRow,
    ReelKindDB,
    SessionRow,
    SessionStateDB,
    VideoAssetRow,
)


def session_to_domain(row: SessionRow) -> Session:
    return Session(
        id=row.id,
        language=row.language,
        theme_id=row.theme_id,
        state=SessionState(row.state.value),
        capture_ref=row.capture_ref,
        created_at=row.created_at,
        updated_at=row.updated_at,
    )


def session_from_domain(model: Session) -> dict[str, Any]:
    return {
        "id": model.id,
        "language": model.language,
        "theme_id": model.theme_id,
        "state": SessionStateDB(model.state.value),
        "capture_ref": model.capture_ref,
        "created_at": model.created_at,
        "updated_at": model.updated_at,
    }


def _is_rtl(language: str) -> bool:
    """Best-effort RTL detection for a single ISO 639-1 code.

    Pure data-layer helper: tells the frontend whether the experience's
    localized strings should render right-to-left. Default languages we
    care about right now are English (LTR) and Arabic (RTL).
    """
    return language.lower() in {"ar", "he", "fa", "ur"}


def experience_to_domain(row: ExperienceRow) -> Experience:
    supported = tuple(row.supported_languages_json or ("en",))
    # If any supported language is RTL, the experience is marked RTL.
    rtl = bool(row.rtl_text) or any(_is_rtl(lang) for lang in supported)
    return Experience(
        id=row.id,
        display_name=row.display_name,
        description=row.description,
        duration_sec=row.duration_sec,
        fps=row.fps,
        resolution=row.resolution,
        aspect_ratio=row.aspect_ratio,
        thumbnail_url=row.thumbnail_url,
        enabled=row.enabled,
        display_order=row.display_order,
        prompt=row.prompt,
        negative_prompt=row.negative_prompt,
        visual_style=VisualStyle(
            aesthetic=row.style_aesthetic,
            palette_name=row.style_palette_name,
            keywords=tuple(row.style_keywords_json or ()),
            lighting=row.style_lighting,
            texture=row.style_texture,
        ),
        motion=MotionConfig(
            strength=row.motion_strength,
            camera_motion=row.motion_camera_motion,
            easing=row.motion_easing,
            intensity=row.motion_intensity,
            loop=row.motion_loop,
        ),
        model_params=ModelParams(
            num_inference_steps=row.model_num_inference_steps,
            guidance_scale=row.model_guidance_scale,
            motion_bucket_id=row.model_motion_bucket_id,
            seed_policy=row.model_seed_policy,
            fixed_seed=row.model_fixed_seed,
            strength=row.model_strength,
            extra=dict(row.model_extra_json or {}),
        ),
        theme=ExperienceTheme(
            palette=dict(row.palette_json or {}),
            background_music=row.background_music,
        ),
        metadata=dict(row.metadata_json or {}),
        localized_names=LocalizedText(
            translations=dict(row.localized_names_json or {}),
            rtl=rtl,
        ),
        localized_descriptions=LocalizedText(
            translations=dict(row.localized_descriptions_json or {}),
            rtl=rtl,
        ),
        supported_languages=supported,
        default_language=row.default_language,
        rtl_text=rtl,
    )


def experience_to_row(model: Experience) -> ExperienceRow:
    return ExperienceRow(
        id=model.id,
        display_name=model.display_name,
        description=model.description,
        duration_sec=model.duration_sec,
        fps=model.fps,
        resolution=model.resolution,
        aspect_ratio=model.aspect_ratio,
        thumbnail_url=model.thumbnail_url,
        enabled=model.enabled,
        display_order=model.display_order,
        prompt=model.prompt,
        negative_prompt=model.negative_prompt,
        style_aesthetic=model.visual_style.aesthetic,
        style_palette_name=model.visual_style.palette_name,
        style_keywords_json=list(model.visual_style.keywords),
        style_lighting=model.visual_style.lighting,
        style_texture=model.visual_style.texture,
        motion_strength=model.motion.strength,
        motion_camera_motion=model.motion.camera_motion,
        motion_easing=model.motion.easing,
        motion_intensity=model.motion.intensity,
        motion_loop=model.motion.loop,
        model_num_inference_steps=model.model_params.num_inference_steps,
        model_guidance_scale=model.model_params.guidance_scale,
        model_motion_bucket_id=model.model_params.motion_bucket_id,
        model_seed_policy=model.model_params.seed_policy,
        model_fixed_seed=model.model_params.fixed_seed,
        model_strength=model.model_params.strength,
        model_extra_json=dict(model.model_params.extra),
        palette_json=dict(model.theme.palette),
        background_music=model.theme.background_music,
        metadata_json=dict(model.metadata),
        localized_names_json=dict(model.localized_names.translations),
        localized_descriptions_json=dict(model.localized_descriptions.translations),
        supported_languages_json=list(model.supported_languages),
        default_language=model.default_language,
        rtl_text=model.rtl_text,
    )


def job_to_domain(row: GenerationJobRow) -> GenerationJob:
    output: VideoAsset | None = None
    if row.output_key and row.output_url:
        output = VideoAsset(
            key=row.output_key,
            url=row.output_url,
            duration_sec=row.output_duration_sec or 0.0,
            codec=VideoCodec(row.output_codec) if row.output_codec else VideoCodec.H264,
            size_bytes=row.output_size_bytes,
            width=row.output_width,
            height=row.output_height,
            fps=row.output_fps,
            checksum_sha256=row.output_checksum,
        )
    return GenerationJob(
        id=row.id,
        session_id=row.session_id,
        experience_id=row.experience_id,
        provider_id=row.provider_id,
        state=GenerationJobState(row.state.value),
        attempts=row.attempts,
        max_attempts=row.max_attempts,
        input_ref=row.input_ref,
        output=output,
        progress=row.progress,
        error_code=row.error_code,
        error_message=row.error_message,
        provider_job_id=row.provider_job_id,
        idempotency_key=row.idempotency_key,
        timeout_ms=row.timeout_ms,
        queued_latency_ms=row.queued_latency_ms,
        processing_latency_ms=row.processing_latency_ms,
        generation_latency_ms=row.generation_latency_ms,
        post_processing_latency_ms=row.post_processing_latency_ms,
        encoding_latency_ms=row.encoding_latency_ms,
        total_latency_ms=row.total_latency_ms,
        queued_at=row.queued_at,
        processing_at=row.processing_at,
        generating_at=row.generating_at,
        post_processing_at=row.post_processing_at,
        encoding_at=row.encoding_at,
        created_at=row.created_at,
        updated_at=row.updated_at,
        started_at=row.started_at,
        finished_at=row.finished_at,
    )


def job_from_domain(model: GenerationJob) -> dict[str, Any]:
    data: dict[str, Any] = {
        "id": model.id,
        "session_id": model.session_id,
        "experience_id": model.experience_id,
        "provider_id": model.provider_id,
        "state": JobStateDB(model.state.value),
        "attempts": model.attempts,
        "max_attempts": model.max_attempts,
        "input_ref": model.input_ref,
        "progress": model.progress,
        "error_code": model.error_code,
        "error_message": model.error_message,
        "provider_job_id": model.provider_job_id,
        "idempotency_key": model.idempotency_key,
        "timeout_ms": model.timeout_ms,
        "queued_latency_ms": model.queued_latency_ms,
        "processing_latency_ms": model.processing_latency_ms,
        "generation_latency_ms": model.generation_latency_ms,
        "post_processing_latency_ms": model.post_processing_latency_ms,
        "encoding_latency_ms": model.encoding_latency_ms,
        "total_latency_ms": model.total_latency_ms,
        "queued_at": model.queued_at,
        "processing_at": model.processing_at,
        "generating_at": model.generating_at,
        "post_processing_at": model.post_processing_at,
        "encoding_at": model.encoding_at,
        "started_at": model.started_at,
        "finished_at": model.finished_at,
    }
    if model.output is not None:
        data["output_key"] = model.output.key
        data["output_url"] = model.output.url
        data["output_duration_sec"] = model.output.duration_sec
        data["output_codec"] = model.output.codec.value
        data["output_size_bytes"] = model.output.size_bytes
        data["output_width"] = model.output.width
        data["output_height"] = model.output.height
        data["output_fps"] = model.output.fps
        data["output_checksum"] = model.output.checksum_sha256
    return data


def reel_item_to_domain(row: ReelItemRow) -> ReelItem:
    return ReelItem(
        id=row.id,
        kind=ReelItemKind(row.kind.value),
        src=row.src,
        title=row.title,
        duration_sec=row.duration_sec,
        created_at=row.created_at.timestamp() if row.created_at else 0.0,
    )


def reel_item_from_domain(model: ReelItem) -> dict[str, Any]:
    return {
        "id": model.id,
        "kind": ReelKindDB(model.kind.value),
        "src": model.src,
        "title": model.title,
        "duration_sec": model.duration_sec,
    }


def video_asset_to_row(asset: VideoAsset) -> VideoAssetRow:
    return VideoAssetRow(
        key=asset.key,
        url=asset.url,
        duration_sec=asset.duration_sec,
        codec=asset.codec.value,
        size_bytes=asset.size_bytes,
        width=asset.width,
        height=asset.height,
        fps=asset.fps,
        checksum_sha256=asset.checksum_sha256,
    )


def video_asset_to_domain(row: VideoAssetRow) -> VideoAsset:
    codec = _VideoCodec(row.codec) if row.codec else _VideoCodec.H264
    return VideoAsset(
        key=row.key,
        url=row.url,
        duration_sec=row.duration_sec,
        codec=codec,
        size_bytes=row.size_bytes,
        width=row.width,
        height=row.height,
        fps=row.fps,
        checksum_sha256=row.checksum_sha256,
    )