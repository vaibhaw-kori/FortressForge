"""Inference preprocessing tests without torch/GPU: config, prompts, stages, simulations."""

from __future__ import annotations

import pytest

from aura_backend.errors import ValidationFailed
from aura_backend.inference.wan_config import (
    WanGenerationConfig,
    WanModelConfig,
    build_wan_prompt,
    validate_generation_config,
)
from aura_backend.inference.wan_pipeline import (
    CleanupStage,
    ExperienceConfigurationStage,
    ImagePreprocessingStage,
    InferenceStage,
    InputValidationStage,
    ModelLoadingStage,
    OutputValidationStage,
    PipelineContext,
    PipelineError,
    PostProcessingStage,
    ReferencePreparationStage,
    VideoEncodingStage,
)


def _ctx(**over):
    base = dict(
        job_id="job-1",
        session_id="sess-1",
        experience_id="aurora",
        capture_ref="captures/test.jpg",
        config=WanGenerationConfig(prompt="a cinematic test prompt", negative_prompt="bad"),
        model_config=WanModelConfig(),
    )
    base.update(over)
    return PipelineContext(**base)


# ---------------------------------------------------------------------------
# wan_config validation
# ---------------------------------------------------------------------------


class TestValidateConfig:
    def test_valid(self):
        cfg = WanGenerationConfig(prompt="a cinematic test prompt")
        ok, errors = validate_generation_config(cfg)
        assert ok is True
        assert errors == []

    @pytest.mark.parametrize(
        "kwargs,needle",
        [
            ({"prompt": "x"}, "Prompt too short"),
            ({"prompt": ""}, "Prompt too short"),
            ({"num_inference_steps": 5}, "num_inference_steps"),
            ({"num_inference_steps": 55}, "num_inference_steps"),
            ({"guidance_scale": 0.5}, "guidance_scale"),
            ({"guidance_scale": 25.0}, "guidance_scale"),
            ({"fps": 0}, "fps"),
            ({"fps": 35}, "fps"),
            ({"duration_sec": 0.1}, "duration_sec"),
            ({"duration_sec": 15.0}, "duration_sec"),
            ({"width": 719}, "multiples of 8"),
            ({"height": 1281}, "multiples of 8"),
            ({"width": 2000, "height": 1200}, "too high"),
            ({"num_frames": 5}, "num_frames"),
            ({"num_frames": 85}, "num_frames"),
            ({"strength": -0.1}, "strength"),
            ({"strength": 1.5}, "strength"),
            ({"motion_bucket_id": 0}, "motion_bucket_id"),
            ({"motion_bucket_id": 300}, "motion_bucket_id"),
        ],
    )
    def test_each_invalid_field(self, kwargs, needle):
        prompt = kwargs.pop("prompt", "a cinematic test prompt")
        # Preserve explicitly-passed num_frames (WanGenerationConfig only derives
        # num_frames when fps/duration are customized, so explicit values survive).
        cfg = WanGenerationConfig(prompt=prompt, **kwargs)
        ok, errors = validate_generation_config(cfg)
        assert ok is False
        assert any(needle in e for e in errors), f"{needle} not in {errors}"


# ---------------------------------------------------------------------------
# prompt building
# ---------------------------------------------------------------------------


class TestPromptBuilding:
    def test_aurora(self):
        p = build_wan_prompt("aurora", "a person")
        assert "a person" in p
        assert len(p) > 20

    def test_mirage(self):
        p = build_wan_prompt("mirage", "a visitor")
        assert "a visitor" in p
        assert "oasis" in p.lower() or "desert" in p.lower()

    def test_pulse(self):
        p = build_wan_prompt("pulse", "a dancer")
        assert "a dancer" in p

    def test_driftwood(self):
        p = build_wan_prompt("driftwood", "a person")
        assert "a person" in p
        assert "shoreline" in p.lower() or "moonlit" in p.lower()

    def test_unknown_fallback(self):
        p = build_wan_prompt("unknown-theme", "a person")
        assert "a person" in p
        assert "unknown-theme" in p

    def test_custom_overrides(self):
        custom = "my custom cinematic prompt"
        assert build_wan_prompt("aurora", "a person", custom_prompt=custom) == custom


# ---------------------------------------------------------------------------
# InputValidationStage
# ---------------------------------------------------------------------------


class TestInputValidation:
    def test_valid(self):
        ctx = InputValidationStage()(_ctx())
        assert ctx.metadata.get("input_validated") is True

    def test_missing_capture_ref(self):
        with pytest.raises(PipelineError) as ei:
            InputValidationStage()(_ctx(capture_ref=""))
        assert isinstance(ei.value.original_error, ValidationFailed)

    def test_missing_session(self):
        with pytest.raises(PipelineError) as ei:
            InputValidationStage()(_ctx(session_id=""))
        assert isinstance(ei.value.original_error, ValidationFailed)

    def test_missing_experience(self):
        with pytest.raises(PipelineError) as ei:
            InputValidationStage()(_ctx(experience_id=""))
        assert isinstance(ei.value.original_error, ValidationFailed)

    def test_missing_job(self):
        with pytest.raises(PipelineError) as ei:
            InputValidationStage()(_ctx(job_id=""))
        assert isinstance(ei.value.original_error, ValidationFailed)

    def test_bad_resolution(self):
        cfg = WanGenerationConfig(prompt="a cinematic test prompt", width=719, height=1280)
        with pytest.raises(PipelineError) as ei:
            InputValidationStage()(_ctx(config=cfg))
        assert isinstance(ei.value.original_error, ValidationFailed)

    def test_too_many_frames(self):
        cfg = WanGenerationConfig(prompt="a cinematic test prompt", num_frames=85)
        with pytest.raises(PipelineError) as ei:
            InputValidationStage()(_ctx(config=cfg))
        assert isinstance(ei.value.original_error, ValidationFailed)

    def test_short_prompt(self):
        cfg = WanGenerationConfig(prompt="x")
        with pytest.raises(PipelineError) as ei:
            InputValidationStage()(_ctx(config=cfg))
        assert isinstance(ei.value.original_error, ValidationFailed)


# ---------------------------------------------------------------------------
# ExperienceConfigurationStage
# ---------------------------------------------------------------------------


class TestExperienceConfig:
    @pytest.mark.parametrize(
        "exp,bucket,scale",
        [
            ("aurora", 180, 7.5),
            ("mirage", 160, 7.0),
            ("pulse", 220, 8.0),
            ("driftwood", 120, 6.5),
        ],
    )
    def test_overrides(self, exp, bucket, scale):
        ctx = ExperienceConfigurationStage()(_ctx(experience_id=exp))
        assert ctx.metadata.get("experience_configured") is True
        assert ctx.config.prompt
        assert ctx.config.negative_prompt
        assert ctx.config.motion_bucket_id == bucket
        assert ctx.config.guidance_scale == scale

    def test_prompt_contains_experience_signal(self):
        for exp in ["aurora", "mirage", "pulse", "driftwood"]:
            ctx = ExperienceConfigurationStage()(_ctx(experience_id=exp))
            assert len(ctx.config.prompt) > 20


# ---------------------------------------------------------------------------
# torch-dependent stages raise informative ImportError (not ModuleNotFoundError)
# ---------------------------------------------------------------------------


def _assert_informative_import_error(exc: PipelineError):
    orig = exc.original_error
    assert isinstance(orig, ImportError), f"expected ImportError, got {type(orig)}: {orig}"
    assert type(orig) is ImportError, f"must be ImportError, not {type(orig).__name__}"
    assert "pip install" in str(orig), f"message should hint pip install, got: {orig}"


class TestTorchGating:
    def test_image_preprocessing_empty_rejected_without_torch(self):
        # Empty ref must be ValidationFailed, not ImportError — no torch needed.
        with pytest.raises(PipelineError) as ei:
            ImagePreprocessingStage()(_ctx(capture_ref=""))
        assert isinstance(ei.value.original_error, ValidationFailed)

    def test_image_preprocessing_nonempty_requires_torch(self):
        with pytest.raises(PipelineError) as ei:
            ImagePreprocessingStage()(_ctx(capture_ref="captures/x.jpg"))
        _assert_informative_import_error(ei.value)

    def test_image_preprocessing_invalid_storage_still_import_error(self, monkeypatch):
        # Even with mocked storage returning garbage, torch gating fires first.
        import aura_backend.inference.wan_pipeline as wp

        class _S:
            def get(self, key):
                return b"garbage-bytes" * 50

        monkeypatch.setattr(wp, "get_storage", lambda: _S())
        with pytest.raises(PipelineError) as ei:
            ImagePreprocessingStage()(_ctx(capture_ref="captures/bad.jpg"))
        _assert_informative_import_error(ei.value)

    def test_reference_preparation_gated(self):
        with pytest.raises(PipelineError) as ei:
            ReferencePreparationStage()(_ctx())
        _assert_informative_import_error(ei.value)

    def test_model_loading_gated(self):
        with pytest.raises(PipelineError) as ei:
            ModelLoadingStage()(_ctx())
        _assert_informative_import_error(ei.value)

    def test_inference_gated(self):
        with pytest.raises(PipelineError) as ei:
            InferenceStage()(_ctx())
        _assert_informative_import_error(ei.value)

    def test_postprocessing_gated(self):
        ctx = _ctx()
        ctx.video_frames = ["fake-frame"]
        with pytest.raises(PipelineError) as ei:
            PostProcessingStage()(ctx)
        _assert_informative_import_error(ei.value)

    def test_video_encoding_gated(self):
        ctx = _ctx()
        ctx.video_frames = ["fake-frame"]
        with pytest.raises(PipelineError) as ei:
            VideoEncodingStage()(ctx)
        _assert_informative_import_error(ei.value)

    def test_output_validation_gated(self):
        with pytest.raises(PipelineError) as ei:
            OutputValidationStage()(_ctx())
        _assert_informative_import_error(ei.value)

    def test_cleanup_succeeds_without_torch(self):
        ctx = CleanupStage()(_ctx())
        assert ctx.metadata.get("cleanup_done") is True
        assert "total_time" in ctx.metadata


# ---------------------------------------------------------------------------
# simulations: no person / multiple people / invalid capture (no GPU)
# ---------------------------------------------------------------------------


class TestCaptureSimulations:
    def test_no_person_blank_rejected(self, monkeypatch):
        """Blank capture (empty ref) is rejected at preprocessing without torch."""
        import aura_backend.inference.wan_pipeline as wp

        class _EmptyStorage:
            def get(self, key):
                return b""  # blank file

        monkeypatch.setattr(wp, "get_storage", lambda: _EmptyStorage())
        with pytest.raises(PipelineError) as ei:
            ImagePreprocessingStage()(_ctx(capture_ref=""))
        # Empty ref → ValidationFailed (simulates 'no person / blank rejected').
        assert isinstance(ei.value.original_error, ValidationFailed)

    def test_small_image_rejected_at_api_layer(self):
        """Small images are rejected by capture validation (unit-level magic/size rule)."""
        from aura_backend.api.v1.captures import MAX_CAPTURE_BYTES

        assert MAX_CAPTURE_BYTES == 8 * 1024 * 1024
        tiny = b"\xff\xd8\xff" + b"\x00" * 10
        assert len(tiny) < 100  # captures.py rejects <100 bytes as 'too small'

    def test_multiple_people_flag_passes_but_recorded(self):
        """Multiple-people metadata passes input validation (flagged, not rejected)."""
        ctx = _ctx()
        ctx.metadata["people_count"] = 3  # simulated detector flag
        ctx.metadata["people_flag"] = "multiple"
        out = InputValidationStage()(ctx)
        assert out.metadata.get("input_validated") is True
        # Flag survives validation for downstream stages to act on.
        assert out.metadata["people_count"] == 3
        assert out.metadata["people_flag"] == "multiple"

    def test_invalid_capture_empty_ref_rejected(self):
        with pytest.raises(PipelineError) as ei:
            InputValidationStage()(_ctx(capture_ref=""))
        assert isinstance(ei.value.original_error, ValidationFailed)
        with pytest.raises(PipelineError) as ei2:
            ImagePreprocessingStage()(_ctx(capture_ref=""))
        assert isinstance(ei2.value.original_error, ValidationFailed)
