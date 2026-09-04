"""Experience routes (API v1)."""

from __future__ import annotations

from fastapi import APIRouter, Depends, Query, status
from sqlalchemy.orm import Session as OrmSession

from ...db import get_db
from ...domain import DEFAULT_LANGUAGE, Experience
from ...services import ExperienceService
from .schemas import (
    ExperienceListResponse,
    ExperienceListQuery,
    ExperienceResponse,
    ExperienceThemeDTO,
    LocalizedTextDTO,
    ModelParamsDTO,
    MotionConfigDTO,
    VisualStyleDTO,
)

router = APIRouter(prefix="/experiences", tags=["experiences"])


def _service(db: OrmSession = Depends(get_db)) -> ExperienceService:
    return ExperienceService(db)


def _resolve_language(exp: Experience, language: str | None) -> str:
    """Pick the best language for this request.

    Order:
    1. Caller's `language` if it's in `supported_languages`.
    2. Otherwise the experience's `default_language`.
    """
    if language and exp.supports_language(language):
        return language
    return exp.default_language or DEFAULT_LANGUAGE


def _localized_dto(exp: Experience, kind: str, language: str) -> LocalizedTextDTO:
    """Resolve a localized text field for a given language.

    `kind` is "name" or "description" — selects which LocalizedText to use.
    The `rtl` flag travels with the text so the frontend can render
    right-to-left strings correctly without re-deriving the rule.
    """
    text = exp.localized_names if kind == "name" else exp.localized_descriptions
    value = text.get(language, fallback_language=exp.default_language)
    fallback_used = exp.default_language if language != exp.default_language else language
    if not value:
        # Final fallback: experience's primary field.
        value = exp.display_name if kind == "name" else exp.description
        fallback_used = exp.default_language
    return LocalizedTextDTO(
        language=language,
        value=value,
        fallback_language=fallback_used,
        rtl=text.rtl or exp.rtl_text,
    )


def _to_dto(exp: Experience, language: str | None) -> ExperienceResponse:
    lang = _resolve_language(exp, language)
    return ExperienceResponse(
        id=exp.id,
        display_name=exp.localized_name(lang),
        description=exp.localized_description(lang),
        duration_sec=exp.duration_sec,
        fps=exp.fps,
        resolution=exp.resolution,
        aspect_ratio=exp.aspect_ratio,
        thumbnail_url=exp.thumbnail_url,
        enabled=exp.enabled,
        display_order=exp.display_order,
        prompt=exp.prompt,
        negative_prompt=exp.negative_prompt,
        visual_style=VisualStyleDTO(
            aesthetic=exp.visual_style.aesthetic,
            palette_name=exp.visual_style.palette_name,
            keywords=list(exp.visual_style.keywords),
            lighting=exp.visual_style.lighting,
            texture=exp.visual_style.texture,
        ),
        motion=MotionConfigDTO(
            strength=exp.motion.strength,
            camera_motion=exp.motion.camera_motion,
            easing=exp.motion.easing,
            intensity=exp.motion.intensity,
            loop=exp.motion.loop,
        ),
        model_params=ModelParamsDTO(
            num_inference_steps=exp.model_params.num_inference_steps,
            guidance_scale=exp.model_params.guidance_scale,
            motion_bucket_id=exp.model_params.motion_bucket_id,
            seed_policy=exp.model_params.seed_policy,
            fixed_seed=exp.model_params.fixed_seed,
            strength=exp.model_params.strength,
            extra=dict(exp.model_params.extra),
        ),
        theme=ExperienceThemeDTO(
            palette=exp.theme.palette,
            background_music=exp.theme.background_music,
        ),
        metadata=exp.metadata,
        localized_names=_localized_dto(exp, "name", lang),
        localized_descriptions=_localized_dto(exp, "description", lang),
        supported_languages=list(exp.supported_languages),
        default_language=exp.default_language,
        rtl_text=exp.rtl_text,
    )


@router.get("", response_model=ExperienceListResponse)
async def list_experiences(
    enabled_only: bool = Query(default=True, description="Hide disabled experiences"),
    language: str | None = Query(default=None, max_length=8, description="BCP-47 code"),
    svc: ExperienceService = Depends(_service),
) -> ExperienceListResponse:
    items = svc.list(enabled_only=enabled_only)
    return ExperienceListResponse(
        items=[_to_dto(e, language) for e in items]
    )


@router.get(
    "/{experience_id}",
    response_model=ExperienceResponse,
    responses={status.HTTP_404_NOT_FOUND: {"description": "Experience not found"}},
)
async def get_experience(
    experience_id: str,
    language: str | None = Query(default=None, max_length=8, description="BCP-47 code"),
    svc: ExperienceService = Depends(_service),
) -> ExperienceResponse:
    exp = svc.get(experience_id)
    return _to_dto(exp, language)


# Public query-schema export for documentation.
__all__ = ["router", "ExperienceListQuery"]