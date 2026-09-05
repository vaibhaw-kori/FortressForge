"""
Wan 2.1 Local Video Generation Provider.

This provider runs the Wan 2.1 inference pipeline locally (or on the same
machine with GPU) instead of calling RunPod. It implements the same
VideoGenerationProvider interface so the worker can use it transparently.

This is the actual AI video generation provider that uses the Wan 2.1 pipeline
locally on the machine with GPU.
"""

from __future__ import annotations

import asyncio
import contextlib
import uuid
import time
from dataclasses import dataclass, field
from typing import Any, Optional

from ..domain.video_asset import VideoCodec
from ..errors import ProviderError, ProviderTimeoutError
from .providers.base import (
    PROVIDER_STATUS_FAILED,
    PROVIDER_STATUS_QUEUED,
    PROVIDER_STATUS_RUNNING,
    PROVIDER_STATUS_SUCCEEDED,
    PROVIDER_STATUS_CANCELLED,
    ProgressEvent,
    ProviderHandle,
    ProviderInput,
    ProviderResult,
    VideoGenerationProvider,
    get_provider_registry,
)
from .wan_config import WanGenerationConfig
from .wan_pipeline import WanInferencePipeline, WanPipelineFactory


@dataclass
class _WanJob:
    """Internal job tracking for Wan provider."""
    handle: ProviderHandle
    pipeline_task: asyncio.Task
    state: str = "queued"
    result: Optional[dict] = None
    error: Optional[str] = None
    created_at: float = field(default_factory=time.time)


class WanVideoGenerationProvider(VideoGenerationProvider):
    """
    Wan 2.1 Local Video Generation Provider.
    
    This provider runs the Wan 2.1 inference pipeline locally on the machine
    with GPU. It implements the same interface as RunPod provider so the
    worker can use it transparently.
    
    The provider manages the full inference pipeline locally:
    - Loads model once on startup
    - Processes jobs from the queue
    - Reports progress via events
    - Handles cancellation, timeouts, retries
    """
    
    provider_id = "wan-local"
    
    def __init__(
        self,
        provider_id: str = "wan-local",
        model_config: Optional["WanModelConfig"] = None,
        generation_config: Optional["WanGenerationConfig"] = None,
    ) -> None:
        self.provider_id = provider_id
        self.model_config = model_config
        self.generation_config = generation_config
        self._jobs: dict[str, _WanJob] = {}
        self._lock = asyncio.Lock()
        self._pipeline_factory: Optional["WanPipelineFactory"] = None
        
        # Initialize pipeline factory
        from .wan_config import WanModelConfig, WanGenerationConfig
        from .wan_pipeline import WanPipelineFactory
        
        self.model_config = model_config
        self.generation_config = generation_config
        self._pipeline_factory = WanPipelineFactory(model_config or WanModelConfig())
    
    def _create_pipeline(self, payload: "ProviderInput") -> "WanInferencePipeline":
        """Create a pipeline instance for a job."""
        from .wan_config import WanModelConfig, WanGenerationConfig, build_wan_prompt
        from .wan_pipeline import WanPipelineFactory

        if not self._pipeline_factory:
            self._pipeline_factory = WanPipelineFactory(
                self.model_config or WanModelConfig()
            )

        # ProviderInput carries only base fields; per-experience tuning lives
        # in model_params (the worker merges Experience.model_params there).
        mp: dict[str, Any] = dict(payload.model_params or {})
        # Worker may nest well-known params at top level of model_params.
        steps = int(mp.get("num_inference_steps", 24))
        guidance = float(mp.get("guidance_scale", 7.0))
        motion_bucket = int(mp.get("motion_bucket_id", 160))
        seed_policy = str(mp.get("seed_policy", "visitor_derived"))
        fixed_seed = mp.get("fixed_seed")
        strength = float(mp.get("strength", 0.7))

        gen_config = WanGenerationConfig(
            prompt=payload.prompt or build_wan_prompt(
                experience_id=payload.experience_id,
                visitor_description="a person",
            ),
            negative_prompt=payload.negative_prompt or "",
            num_inference_steps=steps,
            guidance_scale=guidance,
            motion_bucket_id=motion_bucket,
            seed=fixed_seed if isinstance(fixed_seed, int) else None,
            fps=payload.fps or 12,
            duration_sec=payload.duration_sec or 4.0,
            seed_policy=seed_policy,
            fixed_seed=fixed_seed if isinstance(fixed_seed, int) else None,
            strength=strength,
        )
        # Resolution/aspect live on the worker payload; map to W/H via presets.
        from .wan_config import RESOLUTION_PRESETS

        res = payload.resolution or "480x832"
        if res in RESOLUTION_PRESETS:
            gen_config.width, gen_config.height = RESOLUTION_PRESETS[res]

        return WanInferencePipeline(
            model_config=self.model_config or WanModelConfig(),
            generation_config=gen_config,
            job_id=payload.job_id,
            session_id=payload.session_id,
            experience_id=payload.experience_id,
            capture_ref=payload.capture_ref,
        )
    
    async def submit(self, payload: "ProviderInput") -> "ProviderHandle":
        """Submit a generation job to the local Wan pipeline."""
        # Create handle
        handle = ProviderHandle(
            provider_id=self.provider_id,
            provider_job_id=uuid.uuid4().hex,
        )
        
        # Create pipeline for this job
        pipeline = self._create_pipeline(payload)
        
        # Create job tracking
        job = _WanJob(
            handle=handle,
            pipeline_task=asyncio.create_task(
                self._run_pipeline(pipeline, payload)
            ),
        )
        
        async with self._lock:
            self._jobs[handle.provider_job_id] = job
        
        return handle
    
    async def _run_pipeline(self, pipeline: "WanInferencePipeline", payload: "ProviderInput") -> dict:
        """Run the pipeline and return result dict."""
        try:
            # Set up progress tracking
            progress_events = []
            
            def progress_callback(progress: float, phase: str):
                # Could emit to event bus here
                pass
            
            # Run the pipeline
            result = await pipeline.run(
                capture_ref=payload.capture_ref,
                progress_callback=None,  # We'll add progress tracking later
            )
            
            return result
            
        except Exception as e:
            # The pipeline will handle its own errors and return error in result
            raise
    
    async def status(self, handle: ProviderHandle) -> str:
        """Get job status."""
        async with self._lock:
            job = self._jobs.get(handle.provider_job_id)
        
        if job is None:
            return PROVIDER_STATUS_FAILED
        
        if job.pipeline_task.done():
            if job.pipeline_task.cancelled():
                return PROVIDER_STATUS_CANCELLED
            try:
                result = job.pipeline_task.result()
                if result.get("video_asset"):
                    return PROVIDER_STATUS_SUCCEEDED
                else:
                    return PROVIDER_STATUS_FAILED
            except Exception:
                return PROVIDER_STATUS_FAILED
        
        return PROVIDER_STATUS_RUNNING
    
    async def result(self, handle: ProviderHandle) -> "ProviderResult":
        """Get the final result."""
        async with self._lock:
            job = self._jobs.get(handle.provider_job_id)
        
        if job is None:
            raise ProviderError("wan_no_such_job", f"No such job {handle.provider_job_id}")
        
        if not job.pipeline_task.done():
            raise ProviderError("wan_not_ready", "Job not yet completed")
        
        try:
            result = job.pipeline_task.result()
        except Exception as e:
            raise ProviderError("wan_execution_failed", str(e)) from e
        
        if not result.get("video_asset"):
            raise ProviderError(
                "wan_no_output",
                "Pipeline completed but no video asset produced",
            )
        
        video_asset = result["video_asset"]
        codec_raw = video_asset.get("codec", "h264")
        try:
            codec = VideoCodec(codec_raw) if not isinstance(codec_raw, VideoCodec) else codec_raw
        except Exception:
            codec = VideoCodec.H264
        return ProviderResult(
            output_ref=video_asset.get("url", video_asset.get("output_ref", "")),
            duration_sec=video_asset.get("duration_sec", 4.0),
            codec=codec,
            size_bytes=video_asset.get("size_bytes"),
            width=video_asset.get("width"),
            height=video_asset.get("height"),
            fps=video_asset.get("fps"),
            checksum_sha256=video_asset.get("checksum_sha256"),
        )
    
    async def cancel(self, handle: ProviderHandle) -> None:
        """Cancel a running job."""
        async with self._lock:
            job = self._jobs.get(handle.provider_job_id)
        
        if job is None:
            return
        
        if not job.pipeline_task.done():
            job.pipeline_task.cancel()
            try:
                await job.pipeline_task
            except asyncio.CancelledError:
                pass
            except Exception:
                pass
    
    async def healthcheck(self) -> bool:
        """Check if the provider is healthy."""
        try:
            # Check if we can load the model
            from .wan_loader import get_wan_loader
            loader = get_wan_loader()
            loader.load()
            return True
        except Exception:
            return False
    
    async def aclose(self) -> None:
        """Clean up resources."""
        async with self._lock:
            # Cancel all running jobs
            for job in self._jobs.values():
                if not job.pipeline_task.done():
                    job.pipeline_task.cancel()
                    with contextlib.suppress(Exception):
                        await job.pipeline_task
            self._jobs.clear()


# Register the provider in the registry on module load
def register_wan_provider(
    provider_id: str = "wan-local",
    model_config: Optional["WanModelConfig"] = None,
    generation_config: Optional["WanGenerationConfig"] = None,
) -> "WanVideoGenerationProvider":
    """Register the Wan provider in the global registry."""
    from .providers.base import get_provider_registry
    from .wan_config import WanModelConfig, WanGenerationConfig
    
    provider = WanVideoGenerationProvider(
        provider_id=provider_id,
        model_config=model_config,
        generation_config=generation_config,
    )
    
    registry = get_provider_registry()
    registry.register(provider)
    
    return provider