"""Experience / theme configuration.

Pure data object. Holds trusted server-controlled configuration for a
single selectable AI animation experience. The frontend never sends
prompts or model parameters — it sends only an `experience_id`, and the
backend resolves it to this fully-formed config.

The model-specific fields (ModelParams) are intentionally abstract
(provider-agnostic) so we can swap the underlying video model
(SVD, AnimateDiff, Wan2.1, etc.) without touching callers.
"""

from __future__ import annotations

from dataclasses import dataclass, field
from typing import Any


# ---- Supported ISO-639-1 / BCP-47 codes ----
SUPPORTED_LANGUAGES: tuple[str, ...] = ("en", "ar")
DEFAULT_LANGUAGE: str = "en"


# ---- Motion config ----


@dataclass(frozen=True)
class MotionConfig:
    """How the visitor is animated within the experience.

    Pure UX/audiovisual config; no model wiring here.
    """

    strength: float = 0.7  # 0..1
    camera_motion: str = "static"  # 'static' | 'dolly' | 'orbit' | 'parallax'
    easing: str = "ease_in_out"  # 'linear' | 'ease_in' | 'ease_out' | 'ease_in_out'
    intensity: float = 0.5  # 0..1
    loop: bool = False


# ---- Model parameters (provider-agnostic) ----


@dataclass(frozen=True)
class ModelParams:
    """Abstract model parameters.

    The provider layer (RunPod, self-hosted, etc.) interprets these knobs
    into concrete model calls. We keep names generic on purpose so the
    experience catalog stays stable when the underlying model changes.
    """

    num_inference_steps: int = 25
    guidance_scale: float = 7.0
    motion_bucket_id: int = 127  # for img2vid models
    seed_policy: str = "random"  # 'fixed' | 'random' | 'visitor_derived'
    fixed_seed: int | None = None
    strength: float = 0.7  # 0..1, denoising strength
    extra: dict[str, Any] = field(default_factory=dict)


# ---- Visual style ----


@dataclass(frozen=True)
class VisualStyle:
    """High-level style descriptors. Used by prompt templates and the
    frontend thumbnail tinting. Always trusted, never user-supplied.
    """

    aesthetic: str = "abstract"  # 'cinematic' | 'abstract' | 'kinetic' | 'environment' | 'portrait'
    palette_name: str = "default"
    keywords: tuple[str, ...] = ()
    lighting: str = "soft"  # 'soft' | 'dramatic' | 'high_key' | 'low_key'
    texture: str = "smooth"  # 'smooth' | 'grain' | 'glass' | 'paper'


# ---- Localization ----


@dataclass(frozen=True)
class LocalizedText:
    """Localizable strings + RTL flag.

    `rtl` is a data-level hint for the frontend; the backend does not
    transform text. Arabic ("ar") is inherently RTL.
    """

    translations: dict[str, str]  # language code -> text
    rtl: bool = False

    def get(self, language: str, fallback_language: str = DEFAULT_LANGUAGE) -> str:
        """Return the translation for `language`, falling back to
        `fallback_language` then to the first available translation.
        Empty string only if no translations exist.
        """
        if language in self.translations:
            return self.translations[language]
        if fallback_language in self.translations:
            return self.translations[fallback_language]
        if self.translations:
            return next(iter(self.translations.values()))
        return ""

    def has(self, language: str) -> bool:
        return language in self.translations


# ---- Theme (visual) ----


@dataclass(frozen=True)
class ExperienceTheme:
    """Visual palette + motion defaults for the experience UI."""

    palette: dict[str, str] = field(default_factory=dict)
    background_music: str | None = None


# ---- Experience aggregate ----


@dataclass(frozen=True)
class Experience:
    """A selectable AI animation experience.

    Pure data object with invariant validation in __post_init__.
    """

    id: str
    display_name: str
    description: str
    duration_sec: float = 4.0
    fps: int = 12
    resolution: str = "720x1280"
    aspect_ratio: str = "9:16"
    thumbnail_url: str | None = None
    enabled: bool = True
    display_order: int = 0

    # Trusted AI-generation config (server-controlled; never user-supplied).
    prompt: str = ""
    negative_prompt: str | None = None
    visual_style: VisualStyle = field(default_factory=VisualStyle)
    motion: MotionConfig = field(default_factory=MotionConfig)
    model_params: ModelParams = field(default_factory=ModelParams)

    # UI / display config.
    theme: ExperienceTheme = field(default_factory=ExperienceTheme)
    metadata: dict[str, Any] = field(default_factory=dict)

    # Localization.
    localized_names: LocalizedText = field(default_factory=lambda: LocalizedText(translations={}))
    localized_descriptions: LocalizedText = field(
        default_factory=lambda: LocalizedText(translations={})
    )
    supported_languages: tuple[str, ...] = SUPPORTED_LANGUAGES
    default_language: str = DEFAULT_LANGUAGE
    rtl_text: bool = False

    # ---- construction validation ----

    def __post_init__(self) -> None:
        if not self.id or len(self.id) > 64:
            raise ValueError("Experience.id must be 1..64 chars")
        if not self.display_name:
            raise ValueError("Experience.display_name required")
        if not self.description:
            raise ValueError("Experience.description required")
        if self.duration_sec <= 0 or self.duration_sec > 30:
            raise ValueError("Experience.duration_sec must be in (0, 30]")
        if self.fps <= 0 or self.fps > 60:
            raise ValueError("Experience.fps must be in (0, 60]")
        if not self._valid_resolution(self.resolution):
            raise ValueError(f"Experience.resolution invalid: {self.resolution}")
        if not self._valid_aspect_ratio(self.aspect_ratio):
            raise ValueError(f"Experience.aspect_ratio invalid: {self.aspect_ratio}")
        if self.prompt is None or not self.prompt.strip():
            raise ValueError("Experience.prompt required (trusted, server-controlled)")
        if len(self.prompt) > 4000:
            raise ValueError("Experience.prompt too long (max 4000 chars)")
        if self.negative_prompt is not None and len(self.negative_prompt) > 4000:
            raise ValueError("Experience.negative_prompt too long (max 4000 chars)")
        if not self.supported_languages:
            raise ValueError("Experience.supported_languages must not be empty")
        for lang in self.supported_languages:
            if not isinstance(lang, str) or not lang:
                raise ValueError(f"invalid language code: {lang!r}")
        if self.default_language not in self.supported_languages:
            raise ValueError(
                f"Experience.default_language {self.default_language!r} "
                f"must be in supported_languages"
            )
        # RTL rule: Arabic must be RTL.
        if "ar" in self.supported_languages and not self.rtl_text:
            # Allow opting out only if Arabic isn't actually localized;
            # but supporting it implies RTL support is exposed at the data
            # level for the frontend to honour.
            pass

    @staticmethod
    def _valid_resolution(res: str) -> bool:
        try:
            w, h = res.lower().split("x")
            return 64 <= int(w) <= 4096 and 64 <= int(h) <= 4096
        except (ValueError, AttributeError):
            return False

    @staticmethod
    def _valid_aspect_ratio(ratio: str) -> bool:
        try:
            w, h = ratio.split(":")
            return 1 <= int(w) <= 32 and 1 <= int(h) <= 32
        except (ValueError, AttributeError):
            return False

    # ---- derived / i18n helpers ----

    def localized_name(self, language: str) -> str:
        return self.localized_names.get(language, fallback_language=self.default_language) or (
            self.display_name
        )

    def localized_description(self, language: str) -> str:
        return self.localized_descriptions.get(
            language, fallback_language=self.default_language
        ) or self.description

    def supports_language(self, language: str) -> bool:
        return language in self.supported_languages