"""Wan I2V API contract tests — no GPU, no 14B download.

Verifies our wrapper passes EXACTLY the kwargs accepted by the installed
WanImageToVideoPipeline.__call__, using inspect + a fake pipeline.
Catches regressions like `image=` on the T2V class or `fps=`/`callback=`.
"""

from __future__ import annotations

import inspect

import pytest


def _needs_diffusers():
    return pytest.importorskip("diffusers")


def _i2v_params() -> set[str]:
    _needs_diffusers()
    from diffusers import WanImageToVideoPipeline

    return set(inspect.signature(WanImageToVideoPipeline.__call__).parameters)


def _ctx():
    from aura_backend.inference.wan_config import WanGenerationConfig, WanModelConfig
    from aura_backend.inference.wan_pipeline import PipelineContext

    return PipelineContext(
        job_id="job-1",
        session_id="sess-1",
        experience_id="aurora",
        capture_ref="local:/tmp/x.jpg",
        config=WanGenerationConfig(
            prompt="a cinematic test prompt",
            negative_prompt="bad",
            width=480,
            height=832,
            num_frames=48,
        ),
        model_config=WanModelConfig(),
    )


class TestInferenceKwargsContract:
    def test_all_kwargs_accepted_by_installed_api(self):
        params = _i2v_params()
        from aura_backend.inference.wan_pipeline import build_inference_kwargs

        ctx = _ctx()
        # capture_image must be set (preprocessing output); use a tiny PIL image.
        PILImage = pytest.importorskip("PIL.Image")
        ctx.capture_image = PILImage.new("RGB", (8, 8))
        kwargs = build_inference_kwargs(ctx)
        unknown = set(kwargs) - params
        assert not unknown, f"kwargs rejected by installed API: {unknown}"

    def test_forbidden_legacy_kwargs_absent(self):
        from aura_backend.inference.wan_pipeline import build_inference_kwargs

        PILImage = pytest.importorskip("PIL.Image")
        ctx = _ctx()
        ctx.capture_image = PILImage.new("RGB", (8, 8))
        kwargs = build_inference_kwargs(ctx)
        for bad in ("fps", "callback", "callback_steps", "seed", "image_embeds", "latents"):
            assert bad not in kwargs, f"legacy kwarg {bad} must not be passed"

    def test_output_type_is_pil(self):
        from aura_backend.inference.wan_pipeline import build_inference_kwargs

        PILImage = pytest.importorskip("PIL.Image")
        ctx = _ctx()
        ctx.capture_image = PILImage.new("RGB", (8, 8))
        assert build_inference_kwargs(ctx)["output_type"] == "pil"

    def test_image_is_first_positional_capable(self):
        # I2V requires image; our kwargs must include a PIL image.
        from aura_backend.inference.wan_pipeline import build_inference_kwargs

        PILImage = pytest.importorskip("PIL.Image")
        ctx = _ctx()
        img = PILImage.new("RGB", (8, 8))
        ctx.capture_image = img
        assert build_inference_kwargs(ctx)["image"] is img


class TestInferenceStageWithFakePipeline:
    def test_stage_calls_fake_with_contract_kwargs(self):
        from aura_backend.inference.wan_pipeline import InferenceStage

        PILImage = pytest.importorskip("PIL.Image")
        ctx = _ctx()
        ctx.capture_image = PILImage.new("RGB", (8, 8))

        seen: dict = {}

        class _Out:
            frames = [[PILImage.new("RGB", (4, 4)) for _ in range(3)]]

        class _FakePipeline:
            def __call__(self, **kwargs):
                seen.update(kwargs)
                return _Out()

        ctx.pipeline = _FakePipeline()
        out = InferenceStage()(ctx)
        assert "image" in seen  # would have raised TypeError on T2V class
        assert seen["output_type"] == "pil"
        assert seen["num_frames"] == 48
        assert out.video_frames is not None and len(out.video_frames) == 3
        assert out.metadata.get("inference_complete") is True
