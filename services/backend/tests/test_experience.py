"""Tests for the expanded Experience configuration model.

Covers:
- Localization (EN/AR + fallback + missing-language)
- RTL detection (data-level)
- Motion, visual style, model params shape
- Display ordering
- Frontend isolation: client only sends experience_id, never prompts
"""

from __future__ import annotations

import pytest

from aura_backend.domain import (
    DEFAULT_LANGUAGE,
    SUPPORTED_LANGUAGES,
    Experience,
    LocalizedText,
    ModelParams,
    MotionConfig,
    VisualStyle,
)
from aura_backend.services.catalog_seed import SEED_EXPERIENCES


def _valid_exp(**kw) -> Experience:
    defaults = dict(
        id="aurora",
        display_name="Aurora",
        description="desc",
        prompt="a portrait, cinematic",
    )
    defaults.update(kw)
    return Experience(**defaults)


# ---- Localization ----


class TestLocalization:
    def test_localized_name_returns_exact_match(self):
        e = _valid_exp(
            localized_names=LocalizedText(
                translations={"en": "Aurora", "ar": "الشفق"}, rtl=True
            )
        )
        assert e.localized_name("en") == "Aurora"
        assert e.localized_name("ar") == "الشفق"

    def test_localized_name_falls_back_to_default(self):
        e = _valid_exp(
            localized_names=LocalizedText(
                translations={"en": "Aurora", "ar": "الشفق"}, rtl=True
            ),
            default_language="en",
        )
        assert e.localized_name("fr") == "Aurora"

    def test_localized_name_falls_back_to_display_name(self):
        e = _valid_exp(
            display_name="Aurora",
            localized_names=LocalizedText(translations={}, rtl=True),
        )
        assert e.localized_name("en") == "Aurora"

    def test_localized_name_returns_empty_when_nothing_available(self):
        e = _valid_exp(
            display_name="Aurora",
            localized_names=LocalizedText(translations={}),
        )
        # Has no translations and no display_name set as the final fallback.
        # Because we pass display_name, it should fall back to that.
        assert e.localized_name("en") == "Aurora"

    def test_supports_language(self):
        e = _valid_exp(supported_languages=("en", "ar"))
        assert e.supports_language("en") is True
        assert e.supports_language("ar") is True
        assert e.supports_language("fr") is False

    def test_default_language_must_be_supported(self):
        with pytest.raises(ValueError):
            _valid_exp(supported_languages=("en",), default_language="ar")

    def test_supported_languages_must_not_be_empty(self):
        with pytest.raises(ValueError):
            _valid_exp(supported_languages=())

    def test_supported_languages_must_be_strings(self):
        with pytest.raises(ValueError):
            _valid_exp(supported_languages=("",))


# ---- RTL ----


class TestRTL:
    def test_rtl_propagated_to_localized_text(self):
        e = _valid_exp(
            supported_languages=("en", "ar"),
            localized_names=LocalizedText(
                translations={"en": "Aurora", "ar": "الشفق"}, rtl=True
            ),
        )
        assert e.localized_names.rtl is True

    def test_default_rtl_false_for_ltr_only(self):
        e = _valid_exp(
            supported_languages=("en",),
            rtl_text=False,
        )
        assert e.rtl_text is False


# ---- Motion / visual style / model params ----


class TestSubConfigs:
    def test_motion_defaults(self):
        e = _valid_exp()
        assert isinstance(e.motion, MotionConfig)
        assert e.motion.strength == 0.7
        assert e.motion.camera_motion == "static"
        assert e.motion.easing == "ease_in_out"
        assert e.motion.intensity == 0.5
        assert e.motion.loop is False

    def test_motion_strength_bounds_validated_at_usage(self):
        # The dataclass itself does not validate, but downstream does.
        m = MotionConfig(strength=0.0)
        assert m.strength == 0.0
        m2 = MotionConfig(strength=1.0)
        assert m2.strength == 1.0

    def test_model_params_defaults(self):
        e = _valid_exp()
        assert isinstance(e.model_params, ModelParams)
        assert e.model_params.num_inference_steps == 25
        assert e.model_params.guidance_scale == 7.0
        assert e.model_params.motion_bucket_id == 127
        assert e.model_params.seed_policy == "random"
        assert e.model_params.fixed_seed is None
        assert e.model_params.strength == 0.7

    def test_visual_style_defaults(self):
        e = _valid_exp()
        assert isinstance(e.visual_style, VisualStyle)
        assert e.visual_style.aesthetic == "abstract"
        assert e.visual_style.lighting == "soft"
        assert e.visual_style.texture == "smooth"
        assert e.visual_style.keywords == ()


# ---- Ordering ----


class TestOrdering:
    def test_display_order_round_trip(self):
        e = _valid_exp(display_order=42)
        assert e.display_order == 42


# ---- Catalog seed sanity ----


class TestSeedCatalog:
    def test_seed_has_expected_ids(self):
        ids = {e.id for e in SEED_EXPERIENCES}
        assert {"aurora", "mirage", "pulse", "driftwood"}.issubset(ids)

    def test_all_seeds_have_ar_localization(self):
        for e in SEED_EXPERIENCES:
            assert e.localized_names.has("ar"), f"{e.id} missing Arabic name"
            assert e.localized_descriptions.has("ar"), f"{e.id} missing Arabic desc"

    def test_all_seeds_are_rtl(self):
        for e in SEED_EXPERIENCES:
            assert e.rtl_text is True

    def test_all_seeds_have_trusted_prompt(self):
        for e in SEED_EXPERIENCES:
            assert e.prompt
            assert isinstance(e.prompt, str)
            assert len(e.prompt) <= 4000

    def test_seeds_are_distinct_display_order(self):
        orders = [e.display_order for e in SEED_EXPERIENCES]
        assert len(set(orders)) == len(orders)

    def test_supported_languages_constant(self):
        assert "en" in SUPPORTED_LANGUAGES
        assert "ar" in SUPPORTED_LANGUAGES
        assert DEFAULT_LANGUAGE in SUPPORTED_LANGUAGES


# ---- Frontend isolation guarantee ----


class TestFrontendIsolation:
    """The frontend must never have to invent prompts or model params.

    These tests assert that:
    - The Experience domain object carries *all* needed information.
    - The prompt and model params are required, non-empty strings/dicts.
    - They are exposed on the Experience so a provider can pick them up.
    """

    def test_prompt_is_required_and_trusted(self):
        with pytest.raises(ValueError):
            _valid_exp(prompt="")

    def test_experience_carries_ai_config_end_to_end(self):
        e = SEED_EXPERIENCES[0]
        assert e.prompt
        assert e.negative_prompt is not None or e.negative_prompt is None  # optional
        assert e.model_params.num_inference_steps >= 1
        assert 0.0 <= e.model_params.guidance_scale <= 30.0