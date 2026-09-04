"""
Unit tests for Wan inference pipeline (non-GPU logic).

These tests verify the pipeline stages, configuration validation,
and error handling without requiring a GPU.
"""

from __future__ import annotations

import pytest
from unittest.mock import MagicMock, patch, AsyncMock

from aura_backend.inference.wan_config import (
    WanModelConfig,
    WanGenerationConfig,
    WanModelVariant,
    WanPrecision,
    WanSchedulerType,
    DEFAULT_NEGATIVE_PROMPT,
    validate_generation_config,
    build_wan_prompt,
    EXPERIENCE_PROMPT_TEMPLATES,
)
from aura_backend.inference.wan_pipeline import (
    PipelineContext,
    PipelineError,
    InputValidationStage,
    ExperienceConfigurationStage,
    ModelLoadingStage,
    WanInferencePipeline,
    WanPipelineFactory,
)
from aura_backend.errors import ValidationFailed, ProviderError


class TestWanConfig:
    """Tests for Wan configuration classes."""

    def test_model_config_defaults(self):
        config = WanModelConfig()
        assert config.variant == WanModelVariant.WAN_2_1_I2V_14B_720P
        assert config.precision == WanPrecision.BF16
        assert config.scheduler_type == WanSchedulerType.UNIPC

    def test_generation_config_defaults(self):
        config = WanGenerationConfig()
        assert config.num_inference_steps == 28
        assert config.guidance_scale == 7.5
        assert config.motion_bucket_id == 180
        assert config.fps == 12
        assert config.duration_sec == 4.0

    def test_generation_config_validation_success(self):
        config = WanGenerationConfig(
            prompt="test prompt",
            negative_prompt="bad",
            num_inference_steps=28,
            guidance_scale=7.5,
            fps=12,
            duration_sec=4.0,
            width=720,
            height=1280,
        )
        is_valid, errors = validate_generation_config(config)
        assert is_valid
        assert errors == []

    def test_generation_config_validation_failures(self):
        # Test various invalid configurations
        test_cases = [
            ({}, ["Prompt too short"]),
            ({"prompt": "test", "num_inference_steps": 5}, ["num_inference_steps"]),
            ({"prompt": "test", "num_inference_steps": 55}, ["num_inference_steps"]),
            ({"prompt": "test", "guidance_scale": 0.5}, ["guidance_scale"]),
            ({"prompt": "test", "guidance_scale": 25}, ["guidance_scale"]),
            ({"prompt": "test", "fps": 0}, ["fps"]),
            ({"prompt": "test", "fps": 35}, ["fps"]),
            ({"prompt": "test", "duration_sec": 0}, ["duration_sec"]),
            ({"prompt": "test", "duration_sec": 15}, ["duration_sec"]),
            ({"prompt": "test", "width": 719, "height": 1280}, ["multiples of 8"]),
            ({"prompt": "test", "width": 720, "height": 1281}, ["multiples of 8"]),
            ({"prompt": "test", "width": 2000, "height": 1200}, ["too high"]),
            ({"prompt": "test", "num_frames": 5}, ["num_frames"]),
            ({"prompt": "test", "num_frames": 85}, ["num_frames"]),
            ({"prompt": "test", "strength": -0.1}, ["strength"]),
            ({"prompt": "test", "strength": 1.5}, ["strength"]),
            ({"prompt": "test", "motion_bucket_id": 0}, ["motion_bucket_id"]),
            ({"prompt": "test", "motion_bucket_id": 300}, ["motion_bucket_id"]),
        ]
        
        for kwargs, expected_error in test_cases:
            config = WanGenerationConfig(prompt="test prompt", **kwargs)
            is_valid, errors = validate_generation_config(config)
            assert not is_valid
            assert any(expected_error in " ".join(errors) for expected_error in expected_error)


class TestPromptBuilding:
    """Tests for prompt building."""

    def test_build_wan_prompt_known_experiences(self):
        for exp_id in ["aurora", "mirage", "pulse", "driftwood"]:
            prompt = build_wan_prompt(exp_id, "a person")
            assert "a person" in prompt
            assert len(prompt) > 20

    def test_build_wan_prompt_unknown_experience(self):
        prompt = build_wan_prompt("unknown", "a person")
        assert "a person" in prompt
        assert "unknown" in prompt

    def test_build_wan_prompt_custom_prompt(self):
        custom = "Custom prompt for testing"
        prompt = build_wan_prompt("aurora", "a person", custom_prompt=custom)
        assert prompt == custom

    def test_experience_templates_exist(self):
        expected = {"aurora", "mirage", "pulse", "driftwood"}
        assert set(EXPERIENCE_PROMPT_TEMPLATES.keys()) == expected


class TestPipelineStages:
    """Test pipeline stages (non-GPU logic)."""

    @pytest.fixture
    def mock_context(self):
        ctx = PipelineContext(
            job_id="test-job",
            session_id="test-session",
            experience_id="aurora",
            capture_ref="captures/test.jpg",
            config=WanGenerationConfig(
                prompt="test prompt",
                negative_prompt="bad",
            ),
            model_config=WanModelConfig(),
        )
        return ctx

    def test_input_validation_stage_valid(self, mock_context):
        stage = InputValidationStage()
        ctx = stage(mock_context)
        assert ctx.metadata.get("input_validated") is True

    def test_input_validation_stage_invalid_resolution(self, mock_context):
        mock_context.config.width = 719  # Not multiple of 8
        mock_context.config.height = 1280
        stage = InputValidationStage()
        with pytest.raises(ValidationFailed):
            stage(mock_context)

    def test_input_validation_stage_invalid_frames(self, mock_context):
        mock_context.config.num_frames = 85  # > 81
        stage = InputValidationStage()
        with pytest.raises(ValidationFailed):
            stage(mock_context)

    def test_experience_configuration_stage(self, mock_context):
        stage = ExperienceConfigurationStage()
        ctx = stage(mock_context)
        assert "experience_configured" in ctx.metadata
        assert ctx.config.prompt != ""
        assert "aurora" in ctx.config.prompt.lower()

    def test_experience_configuration_applies_overrides(self, mock_context):
        stage = ExperienceConfigurationStage()
        for exp_id in ["aurora", "mirage", "pulse", "driftwood"]:
            mock_context.experience_id = exp_id
            ctx = stage(mock_context)
            assert ctx.config.motion_bucket_id is not None
            assert ctx.config.guidance_scale is not None


class TestPipelineOrchestrator:
    """Test the pipeline orchestrator logic."""

    @pytest.fixture
    def mock_pipeline_factory(self):
        return WanPipelineFactory()

    def test_create_pipeline(self, mock_pipeline_factory):
        pipeline = mock_pipeline_factory.create_pipeline(
            job_id="test-job",
            session_id="test-session",
            experience_id="aurora",
            capture_ref="captures/test.jpg",
            generation_config=WanGenerationConfig(),
        )
        assert isinstance(pipeline, WanInferencePipeline)

    def test_create_pipeline_from_request(self, mock_pipeline_factory):
        # Mock ProviderInput
        class MockProviderInput:
            job_id = "test-job"
            session_id = "test-session"
            experience_id = "aurora"
            capture_ref = "captures/test.jpg"
            num_inference_steps = 20
            guidance_scale = 6.0
            motion_bucket_id = 150
            fps = 10
            duration_sec = 3.0
            resolution = "480x832"
            aspect_ratio = "9:16"
            provider_id = "test-provider"
            model_params = {}
            idempotency_key = "idem-1"
            fixed_seed = 12345
            strength = 0.5
            seed_policy = "visitor_derived"

        factory = WanPipelineFactory()
        pipeline = factory.create_pipeline_from_request(
            job_id="test-job",
            session_id="test-session",
            experience_id="aurora",
            capture_ref="captures/test.jpg",
            provider_input=MockProviderInput(),
        )
        assert isinstance(pipeline, WanInferencePipeline)


class TestPipelineErrorHandling:
    """Test pipeline error handling."""

    def test_pipeline_error_creation(self):
        error = PipelineError("test_stage", "test message")
        assert error.stage == "test_stage"
        assert "test message" in str(error)

    def test_pipeline_error_with_original(self):
        original = ValueError("original error")
        error = PipelineError("test_stage", "test message", original)
        assert error.original_error is original


class TestPipelineFactory:
    """Test the pipeline factory."""

    def test_create_pipeline(self):
        factory = WanPipelineFactory()
        pipeline = factory.create_pipeline(
            job_id="test",
            session_id="session",
            experience_id="aurora",
            capture_ref="cap.jpg",
            generation_config=WanGenerationConfig(),
        )
        assert isinstance(pipeline, WanInferencePipeline)

def test_create_pipeline_from_request(self):
        factory = WanPipelineFactory()
        
        class MockInput:
            job_id = "job1"
            session_id = "sess1"
            experience_id = "aurora"
            capture_ref = "cap.jpg"
            num_inference_steps = 20
            guidance_scale = 6.0
            motion_bucket_id = 150
            fps = 10
            duration_sec = 3.0
            resolution = "480x832"
            aspect_ratio = "9:16"
            provider_id = "test"
            model_params = {}
            idempotency_key = "abc-1"
            fixed_seed = 42
            strength = 0.5
            seed_policy = "visitor_derived"
        
        pipeline = factory.create_pipeline_from_request(
            job_id="job1",
            session_id="sess1",
            experience_id="aurora",
            capture_ref="cap.jpg",
            provider_input=MockInput(),
        )
        assert isinstance(pipeline, WanInferencePipeline)


class TestWanPipelineFactory:
    """Test WanPipelineFactory."""

    def test_create_pipeline(self):
        factory = WanPipelineFactory()
        pipeline = factory.create_pipeline(
            job_id="test",
            session_id="session",
            experience_id="aurora",
            capture_ref="cap.jpg",
            generation_config=WanGenerationConfig(),
        )
        assert isinstance(pipeline, WanInferencePipeline)
        assert pipeline.job_id == "test"

    def test_factory_with_custom_config(self):
        custom_config = WanModelConfig(variant=WanModelVariant.WAN_2_1_I2V_14B_480P)
        factory = WanPipelineFactory(custom_config)
        pipeline = factory.create_pipeline(
            job_id="test",
            session_id="session",
            experience_id="aurora",
            capture_ref="cap.jpg",
            generation_config=WanGenerationConfig(),
        )
        assert pipeline.model_config.variant == WanModelVariant.WAN_2_1_I2V_14B_480P


if __name__ == "__main__":
    pytest.main([__file__, "-v"])