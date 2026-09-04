"""
Wan 2.1 Inference Pipeline - Stages 1-10.

This module implements the complete inference pipeline as modular stages:
1. Input Validation
2. Image Preprocessing
3. Reference Preparation
5. Experience Configuration
6. Model Loading
7. Inference
8. Post-Processing
9. Video Encoding
10. Output Validation
"""

from __future__ import annotations

import gc
import hashlib
import io
import os
import tempfile
import time
import uuid
from dataclasses import dataclass, field
from pathlib import Path
from typing import Any, Callable, Optional

import torch
import torchvision.transforms as T
from PIL import Image

from .wan_config import (
    WanGenerationConfig,
    WanModelConfig,
    WanPrecision,
    DEFAULT_NEGATIVE_PROMPT,
    validate_generation_config,
)
from .wan_loader import (
    WanModelLoader,
    get_wan_loader,
    inference_mode,
    clear_cuda_cache,
    get_vram_usage,
)

from ..errors import (
    ProviderError,
    ProviderTimeoutError,
    ValidationFailed,
)

from ..domain.video_asset import VideoAsset, VideoCodec
from ..storage import get_storage

# Lazy import for heavy dependencies
try:
    from diffusers import WanPipeline
    import torch
    from PIL import Image
    import numpy as np
except ImportError:
    pass


@dataclass
class PipelineContext:
    """Context passed through all pipeline stages."""
    job_id: str
    session_id: str
    experience_id: str
    capture_ref: str
    config: "WanGenerationConfig"
    model_config: "WanModelConfig"
    capture_image: Any = None
    capture_tensor: Any = None
    pipeline: Any = None
    latents: Any = None
    video_frames: list = field(default_factory=list)
    output_path: Optional[str] = None
    output_url: Optional[str] = None
    video_asset: Optional[Any] = None
    metadata: dict = field(default_factory=dict)
    errors: list = field(default_factory=list)
    warnings: list = field(default_factory=list)
    timings: dict = field(default_factory=dict)
    started_at: float = field(default_factory=time.time)
    seed: Optional[int] = None


# Type alias for stage functions
StageFunc = Callable[["PipelineContext"], "PipelineContext"]


class PipelineError(Exception):
    """Pipeline execution error."""
    def __init__(self, stage: str, message: str, original_error: Exception | None = None):
        self.stage = stage
        self.message = message
        self.original_error = original_error
        super().__init__(f"Pipeline stage '{stage}': {message}")


class PipelineStage:
    """Base class for pipeline stages."""
    
    name: str = "base"
    required: bool = True
    
    def __call__(self, ctx: "PipelineContext") -> "PipelineContext":
        raise NotImplementedError
    
    def _handle_error(self, ctx: "PipelineContext", error: Exception, message: str) -> "PipelineContext":
        ctx.errors.append({
            "stage": self.name,
            "error": str(error),
            "message": message,
            "type": type(error).__name__,
        })
        raise PipelineError(self.name, message, error)


# ============================================================
# Stage 1: Input Validation
# ============================================================

class InputValidationStage(PipelineStage):
    """Stage 1: Validate all inputs before processing."""
    
    name = "input_validation"
    required = True
    
    def __call__(self, ctx: "PipelineContext") -> "PipelineContext":
        try:
            # Validate generation config
            is_valid, errors = validate_generation_config(ctx.config)
            if not is_valid:
                raise ValidationFailed(f"Invalid generation config: {', '.join(errors)}")
            
            # Validate capture reference exists
            if not ctx.capture_ref:
                raise ValidationFailed("Missing capture reference")
            
            # Validate experience ID
            if not ctx.experience_id:
                raise ValidationFailed("Missing experience ID")
            
            # Validate session ID
            if not ctx.session_id:
                raise ValidationFailed("Missing session ID")
            
            # Validate job ID
            if not ctx.job_id:
                raise ValidationFailed("Missing job ID")
            
            # Validate resolution constraints
            if ctx.config.width % 8 != 0 or ctx.config.height % 8 != 0:
                raise ValidationFailed("Width and height must be multiples of 8")
            
            # Validate frame count
            max_frames = 81  # Wan 2.1 max
            if ctx.config.num_frames > 81:
                raise ValidationFailed(f"num_frames exceeds maximum (81)")
            
            ctx.metadata["input_validated"] = True
            return ctx
            
        except Exception as e:
            return self._handle_error(ctx, e, "Input validation failed")


# ============================================================
# Stage 2: Image Preprocessing
# ============================================================

class ImagePreprocessingStage:
    """Stage 2: Load and preprocess the captured image."""
    
    name = "image_preprocessing"
    required = True
    
    def __call__(self, ctx: "PipelineContext") -> "PipelineContext":
        try:
            # Load image from storage
            storage = get_storage()
            image_bytes = storage.get(ctx.capture_ref)
            
            # Load image
            image = Image.open(io.BytesIO(image_bytes)).convert("RGB")
            ctx.metadata["original_size"] = image.size
            ctx.metadata["original_mode"] = image.mode
            
            # Resize to target resolution if needed
            target_width = ctx.config.width
            target_height = ctx.config.height
            
            if image.size != (target_width, target_height):
                # Use high-quality resize
                image = image.resize((target_width, target_height), Image.LANCZOS)
                ctx.warnings.append(f"Resized from {ctx.metadata['original_size']} to ({target_width}, {target_height})")
            
            # Convert to tensor
            transform = T.Compose([
                T.ToTensor(),
                T.Normalize(mean=[0.5, 0.5, 0.5], std=[0.5, 0.5, 0.5]),
            ])
            
            tensor = transform(image).unsqueeze(0)  # [1, 3, H, W]
            ctx.capture_image = image
            ctx.capture_tensor = tensor
            
            ctx.metadata["processed_size"] = (target_width, target_height)
            ctx.metadata["preprocessing_done"] = True
            
            return ctx
            
        except Exception as e:
            return self._handle_error(ctx, e, "Image preprocessing failed")


# ============================================================
# Stage 3: Reference Preparation
# ============================================================

class ReferencePreparationStage:
    """Stage 3: Prepare reference image and conditioning."""
    
    name = "reference_preparation"
    required = True
    
    def __call__(self, ctx: "PipelineContext") -> "PipelineContext":
        try:
            # Prepare the capture tensor for the model
            # Move to correct device and dtype
            device = torch.device("cuda" if torch.cuda.is_available() else "cpu")
            dtype = torch.bfloat16  # Wan uses bfloat16
            
            ctx.capture_tensor = ctx.capture_tensor.to(device=device, dtype=torch.bfloat16)
            
            # Prepare image for Wan pipeline (expects PIL or tensor)
            # The pipeline expects PIL Image or tensor in [0, 1] range
            # Our tensor is normalized to [-1, 1], need to denormalize
            if ctx.capture_tensor is not None:
                # Denormalize from [-1, 1] to [0, 1]
                conditioning_image = (ctx.capture_tensor + 1.0) / 2.0
                conditioning_image = conditioning_image.clamp(0, 1)
                ctx.metadata["reference_prepared"] = True
                ctx.metadata["reference_shape"] = list(ctx.capture_tensor.shape)
            
            return ctx
            
        except Exception as e:
            return self._handle_error(ctx, e, "Reference preparation failed")


# ============================================================
# Stage 4: Experience Configuration
# ============================================================

class ExperienceConfigurationStage:
    """Stage 4: Build generation config from experience."""
    
    name = "experience_configuration"
    required = True
    
    def __call__(self, ctx: "PipelineContext") -> "PipelineContext":
        try:
            from .wan_config import (
                build_wan_prompt,
                DEFAULT_NEGATIVE_PROMPT,
                WanGenerationConfig,
            )
            
            # Build prompt from experience
            prompt = build_wan_prompt(
                experience_id=ctx.experience_id,
                visitor_description="a person",  # Could be enhanced with demographic info
            )
            
            # Update config with experience-specific settings
            ctx.config.prompt = prompt
            ctx.config.negative_prompt = DEFAULT_NEGATIVE_PROMPT
            
            # Apply experience-specific overrides if any
            experience_overrides = {
                "aurora": {"motion_bucket_id": 180, "guidance_scale": 7.5},
                "mirage": {"motion_bucket_id": 160, "guidance_scale": 7.0},
                "pulse": {"motion_bucket_id": 220, "guidance_scale": 8.0},
                "driftwood": {"motion_bucket_id": 120, "guidance_scale": 6.5},
            }
            
            if ctx.experience_id in experience_overrides:
                overrides = experience_overrides[ctx.experience_id]
                for key, value in overrides.items():
                    setattr(ctx.config, key, value)
            
            ctx.metadata["experience_configured"] = True
            ctx.metadata["prompt_length"] = len(prompt)
            
            return ctx
            
        except Exception as e:
            return self._handle_error(ctx, e, "Experience configuration failed")


# ============================================================
# Stage 5: Model Loading
# ============================================================

class ModelLoadingStage:
    """Stage 5: Load or get cached model."""
    
    name = "model_loading"
    required = True
    max_oom_retries = 2
    
    def __init__(self):
        self._loader: Optional[WanModelLoader] = None
    
    def __call__(self, ctx: "PipelineContext") -> "PipelineContext":
        # Try loading with OOM retry logic
        for oom_retry in range(self.max_oom_retries + 1):
            try:
                # Get or create loader
                loader = get_wan_loader(ctx.model_config)
                
                # Load model (uses cache)
                components = ctx.model_config.load()
                
                ctx.pipeline = components.pipeline
                ctx.metadata["model_loaded"] = True
                ctx.metadata["model_load_time"] = getattr(components, "_load_time", None)
                
                return ctx
                
            except torch.cuda.OutOfMemoryError as e:
                if oom_retry < self.max_oom_retries:
                    print(f"OOM on model load attempt {oom_retry + 1}/{self.max_oom_retries}, retrying...")
                    clear_cuda_cache()
                    # Try with CPU offload enabled
                    if not ctx.model_config.enable_offload:
                        ctx.model_config.enable_offload = True
                        ctx.warnings.append("Enabled CPU offload due to OOM")
                        continue
                    elif not ctx.model_config.offload_to_cpu:
                        ctx.model_config.offload_to_cpu = True
                        ctx.warnings.append("Enabled sequential CPU offload due to OOM")
                        continue
                    else:
                        raise ProviderError(
                            "model_load_oom",
                            "Model load OOM after retries and offload enablement",
                        ) from e
            except Exception as e:
                return self._handle_error(ctx, e, "Model loading failed")
        
        # Should not reach here if all retries exhausted
        raise ProviderError("model_load_oom", "Model load OOM after all retries")


# ============================================================
# Stage 6: Inference
# ============================================================

class InferenceStage:
    """Stage 6: Run the actual video generation inference."""
    
    name = "inference"
    required = True
    max_oom_retries = 2
    
    def __call__(self, ctx: "PipelineContext") -> "PipelineContext":
        pipeline = ctx.pipeline
        if not pipeline:
            raise RuntimeError("Pipeline not loaded")
        
        # Prepare generation arguments
        gen_kwargs = {
            "prompt": ctx.config.prompt,
            "negative_prompt": ctx.config.negative_prompt,
            "image": ctx.capture_image,
            "num_inference_steps": ctx.config.num_inference_steps,
            "guidance_scale": ctx.config.guidance_scale,
            "num_frames": ctx.config.num_frames,
            "height": ctx.config.height,
            "width": ctx.config.width,
            "fps": ctx.config.fps,
        }
        
        # Add seed if specified
        if ctx.config.seed is not None:
            gen_kwargs["generator"] = torch.Generator(device="cuda").manual_seed(ctx.config.seed)
            ctx.seed = ctx.config.seed
        else:
            # Generate random seed
            seed = torch.randint(0, 2**32 - 1, (1,)).item()
            gen_kwargs["generator"] = torch.Generator(device="cuda").manual_seed(seed)
            ctx.seed = seed
        
        # Run inference with OOM retry logic
        for oom_retry in range(self.max_oom_retries + 1):
            try:
                # Run inference with progress callback
                start_time = time.time()
                
                def progress_callback(step: int, timestep: int, latents: torch.Tensor):
                    progress = 1.0 - (step / ctx.config.num_inference_steps)
                    # Could emit progress event here
                    pass
                
                with inference_mode():
                    output = pipeline(
                        **gen_kwargs,
                        callback=progress_callback,
                        callback_steps=1,
                    )
                
                inference_time = time.time() - start_time
                ctx.timings["inference"] = inference_time
                ctx.metadata["inference_time"] = inference_time
                
                # Extract frames from output
                if hasattr(output, "frames"):
                    frames = output.frames[0]  # First batch
                else:
                    frames = output[0]
                
                ctx.video_frames = frames
                ctx.metadata["num_frames_generated"] = len(frames)
                ctx.metadata["inference_complete"] = True
                
                return ctx
                
            except torch.cuda.OutOfMemoryError as e:
                if oom_retry < self.max_oom_retries:
                    print(f"OOM on inference attempt {oom_retry + 1}/{self.max_oom_retries}, retrying with reduced settings...")
                    clear_cuda_cache()
                    # Reduce resolution for retry
                    if ctx.config.height > 480:
                        ctx.config.height = max(480, ctx.config.height // 2)
                        ctx.config.width = max(480, ctx.config.width // 2)
                        gen_kwargs["height"] = ctx.config.height
                        gen_kwargs["width"] = ctx.config.width
                        ctx.warnings.append(f"Reduced resolution to {ctx.config.width}x{ctx.config.height} due to OOM")
                        continue
                    elif ctx.config.num_inference_steps > 10:
                        ctx.config.num_inference_steps = max(10, ctx.config.num_inference_steps // 2)
                        gen_kwargs["num_inference_steps"] = ctx.config.num_inference_steps
                        ctx.warnings.append(f"Reduced steps to {ctx.config.num_inference_steps} due to OOM")
                        continue
                    else:
                        # Can't reduce further
                        raise ProviderError(
                            "inference_oom",
                            "Inference OOM after retries and resolution reduction",
                        ) from e
            except Exception as e:
                return self._handle_error(ctx, e, "Inference failed")
        
        # If we exhausted retries
        raise ProviderError("inference_oom_exhausted", "Max OOM retries exceeded")


# ============================================================
# Stage 7: Post-Processing
# ============================================================

class PostProcessingStage:
    """Stage 7: Post-process generated frames."""
    
    name = "post_processing"
    required = True
    
    def __call__(self, ctx: "PipelineContext") -> "PipelineContext":
        try:
            frames = ctx.video_frames
            if not frames:
                raise RuntimeError("No frames generated")
            
            # Convert frames to proper format
            processed_frames = []
            for frame in ctx.video_frames:
                if isinstance(frame, torch.Tensor):
                    # Convert tensor to PIL
                    frame = frame.cpu().float()
                    frame = (frame + 1.0) / 2.0  # Denormalize
                    frame = frame.clamp(0, 1)
                    frame = frame.permute(1, 2, 0).numpy()
                    frame = (frame * 255).astype(np.uint8)
                    frame = Image.fromarray(frame)
                elif isinstance(frame, np.ndarray):
                    frame = Image.fromarray(frame)
                elif not isinstance(frame, Image.Image):
                    raise TypeError(f"Unexpected frame type: {type(frame)}")
                
                processed_frames.append(frame)
            
            ctx.video_frames = processed_frames
            ctx.metadata["post_processing_done"] = True
            ctx.metadata["final_frame_count"] = len(processed_frames)
            
            return ctx
            
        except Exception as e:
            return self._handle_error(ctx, e, "Post-processing failed")


# ============================================================
# Stage 8: Video Encoding
# ============================================================

class VideoEncodingStage:
    """Stage 8: Encode frames to video file."""
    
    name = "video_encoding"
    required = True
    
    def __call__(self, ctx: "PipelineContext") -> "PipelineContext":
        try:
            import cv2
            import numpy as np
            
            frames = ctx.video_frames
            if not frames:
                raise RuntimeError("No frames to encode")
            
            # Create temporary output file
            output_dir = Path(tempfile.gettempdir()) / "aura_generated"
            output_dir.mkdir(parents=True, exist_ok=True)
            
            output_filename = f"{ctx.job_id}.mp4"
            output_path = output_dir / output_filename
            ctx.output_path = str(output_path)
            
            # Get video properties
            first_frame = frames[0]
            if isinstance(first_frame, Image.Image):
                h, w = first_frame.size[1], first_frame.size[0]
            else:
                h, w = first_frame.shape[:2]
            
            fps = ctx.config.fps
            fourcc = cv2.VideoWriter_fourcc(*'mp4v')
            
            writer = cv2.VideoWriter(
                str(output_path),
                fourcc,
                ctx.config.fps,
                (w, h)
            )
            
            for frame in ctx.video_frames:
                if isinstance(frame, Image.Image):
                    frame = cv2.cvtColor(np.array(frame), cv2.COLOR_RGB2BGR)
                elif isinstance(frame, torch.Tensor):
                    frame = frame.cpu().numpy()
                    frame = (frame * 255).astype(np.uint8)
                    frame = cv2.cvtColor(frame, cv2.COLOR_RGB2BGR)
                writer.write(frame)
            
            writer.release()
            
            # Verify output
            if not output_path.exists():
                raise RuntimeError("Video file not created")
            
            file_size = output_path.stat().st_size
            if file_size == 0:
                raise RuntimeError("Generated video file is empty")
            
            ctx.output_path = str(output_path)
            ctx.metadata["output_size_bytes"] = file_size
            ctx.metadata["encoding_done"] = True
            
            # Generate output URL via storage (will be signed if private)
            from ..storage import get_storage

            try:
                # Store immediately to durable storage so temp can be cleaned
                data = output_path.read_bytes()
                storage_key = f"generated/{ctx.job_id[:2]}/{ctx.job_id}.mp4"
                get_storage().put(storage_key, data, content_type="video/mp4")
                ctx.output_url = get_storage().get_url(storage_key)
                ctx.metadata["storage_key"] = storage_key
                ctx.metadata["output_url"] = ctx.output_url
                # Clean temp file after successful store
                try:
                    output_path.unlink(missing_ok=True)
                except Exception:
                    pass
            except Exception:
                # Fallback: keep temp path if storage fails
                ctx.output_url = f"/api/v1/storage/generated/{ctx.job_id[:2]}/{ctx.job_id}.mp4"
                ctx.metadata["output_url"] = ctx.output_url
            
            return ctx
            
        except Exception as e:
            return self._handle_error(ctx, e, "Video encoding failed")


# ============================================================
# Stage 9: Output Validation
# ============================================================

class OutputValidationStage:
    """Stage 9: Validate generated video output."""
    
    name = "output_validation"
    required = True
    
    def __call__(self, ctx: "PipelineContext") -> "PipelineContext":
        try:
            import cv2
            
            if not ctx.output_path or not Path(ctx.output_path).exists():
                raise ValidationFailed("Output video file not found")
            
            # Validate video can be opened and read
            cap = cv2.VideoCapture(ctx.output_path)
            if not cap.isOpened():
                raise ValidationFailed("Cannot open generated video file")
            
            frame_count = int(cap.get(cv2.CAP_PROP_FRAME_COUNT))
            fps = cap.get(cv2.CAP_PROP_FPS)
            width = int(cap.get(cv2.CAP_PROP_FRAME_WIDTH))
            height = int(cap.get(cv2.CAP_PROP_FRAME_HEIGHT))
            cap.release()
            
            # Validate properties
            if frame_count < 8:
                raise ValidationFailed(f"Too few frames: {frame_count}")
            
            if abs(fps - ctx.config.fps) > 1:
                ctx.warnings.append(f"FPS mismatch: expected {ctx.config.fps}, got {fps}")
            
            if width != ctx.config.width or height != ctx.config.height:
                ctx.warnings.append(f"Resolution mismatch: expected {ctx.config.width}x{ctx.config.height}, got {width}x{height}")
            
            # Check file size
            file_size = Path(ctx.output_path).stat().st_size
            if file_size < 1000:  # Less than 1KB is suspicious
                raise ValidationFailed(f"Output file too small: {file_size} bytes")
            
            # Create VideoAsset
            from ..domain.video_asset import VideoAsset, VideoCodec
            ctx.video_asset = VideoAsset(
                key=f"generated/{ctx.job_id[:2]}/{ctx.job_id}.mp4",
                url=ctx.output_url or f"/api/v1/videos/{ctx.job_id}.mp4",
                duration_sec=ctx.config.duration_sec,
                codec=VideoCodec.H264,
                size_bytes=Path(ctx.output_path).stat().st_size,
                width=width,
                height=height,
                fps=ctx.config.fps,
                checksum_sha256=self._compute_checksum(ctx.output_path),
            )
            
            ctx.metadata["output_validated"] = True
            ctx.metadata["validation_passed"] = True
            
            return ctx
            
        except Exception as e:
            return self._handle_error(ctx, e, "Output validation failed")
    
    def _compute_checksum(self, path: str) -> str:
        sha256 = hashlib.sha256()
        with open(path, "rb") as f:
            for chunk in iter(lambda: f.read(8192), b""):
                sha256.update(chunk)
        return sha256.hexdigest()


# ============================================================
# Stage 10: Cleanup
# ============================================================

class CleanupStage:
    """Stage 10: Cleanup temporary files and resources."""
    
    name = "cleanup"
    required = True
    
    def __call__(self, ctx: "PipelineContext") -> "PipelineContext":
        try:
            # Clear CUDA cache
            if torch.cuda.is_available():
                torch.cuda.empty_cache()
                torch.cuda.ipc_collect()
            
            # Force garbage collection
            gc.collect()
            
            # Clear temporary tensors
            ctx.capture_tensor = None
            # Keep video_frames for potential debugging, but could clear
            # ctx.video_frames = []
            
            ctx.metadata["cleanup_done"] = True
            ctx.metadata["total_time"] = time.time() - ctx.started_at
            
            return ctx
            
        except Exception as e:
            # Cleanup errors shouldn't fail the pipeline
            ctx.warnings.append(f"Cleanup warning: {e}")
            return ctx


# ============================================================
# Pipeline Orchestrator
# ============================================================

class WanInferencePipeline:
    """
    Orchestrates the complete inference pipeline.
    """
    
    def __init__(
        self,
        model_config: WanModelConfig,
        generation_config: WanGenerationConfig,
        job_id: str,
        session_id: str,
        experience_id: str,
        capture_ref: str,
    ):
        self.job_id = job_id
        self.session_id = session_id
        self.experience_id = experience_id
        self.capture_ref = capture_ref
        self.model_config = model_config
        self.generation_config = generation_config
        
        # Build pipeline stages
        self.stages: list[PipelineStage] = [
            InputValidationStage(),
            ImagePreprocessingStage(),
            ReferencePreparationStage(),
            ExperienceConfigurationStage(),
            ModelLoadingStage(),
            InferenceStage(),
            PostProcessingStage(),
            VideoEncodingStage(),
            OutputValidationStage(),
            CleanupStage(),
        ]
        
        # Progress callback
        self._progress_callback: Optional[Callable[[float, str], None]] = None
    
    def set_progress_callback(self, callback: Callable[[float, str], None]):
        self._progress_callback = callback
    
    def _emit_progress(self, progress: float, phase: str):
        if self._progress_callback:
            try:
                self._progress_callback(progress, phase)
            except Exception:
                pass
    
    async def run(
        self,
        capture_ref: str,
        progress_callback: Optional[Callable[[float, str], None]] = None,
    ) -> dict:
        """
        Run the complete inference pipeline.
        
        Args:
            capture_ref: Object storage reference for captured image
            progress_callback: Optional progress callback
            
        Returns:
            Dict with result metadata including video_asset
        """
        # Create context
        ctx = PipelineContext(
            job_id=self.job_id,
            session_id=self.session_id,
            experience_id=self.experience_id,
            capture_ref=capture_ref,
            config=self.generation_config,
            model_config=self.model_config,
        )
        
        if progress_callback:
            self._progress_callback = progress_callback
        
        # Execute stages
        ctx = PipelineContext(
            job_id=self.job_id,
            session_id=self.session_id,
            experience_id=self.experience_id,
            capture_ref=capture_ref,
            config=self.generation_config,
            model_config=self.model_config,
        )
        
        for stage in self.stages:
            stage_start = time.time()
            self._emit_progress(0, stage.name)
            
            try:
                ctx = stage(ctx)
                elapsed = time.time() - ctx.started_at
                self._emit_progress(
                    self.stages.index(stage) / len(self.stages),
                    stage.name
                )
            except PipelineError as e:
                ctx.errors.append({
                    "stage": stage.name,
                    "error": str(e),
                    "message": e.message,
                })
                break
            except Exception as e:
                ctx.errors.append({
                    "stage": stage.name,
                    "error": str(e),
                    "type": type(e).__name__,
                })
                break
        
        # Check for errors
        if ctx.errors:
            error = ctx.errors[-1]
            raise ProviderError(
                error["stage"],
                error["message"],
            )
        
        # Compile result
        result = {
            "job_id": self.job_id,
            "session_id": self.session_id,
            "experience_id": self.experience_id,
            "video_asset": ctx.video_asset.to_dict() if ctx.video_asset else None,
            "metadata": ctx.metadata,
            "errors": ctx.errors,
            "warnings": ctx.warnings,
            "timings": ctx.timings,
            "seed": getattr(ctx, 'seed', None),
        }
        
        return result
    
    def _emit_progress(self, progress: float, phase: str):
        if self._progress_callback:
            try:
                self._progress_callback(progress, phase)
            except Exception:
                pass


# ============================================================
# Pipeline Factory
# ============================================================

class WanPipelineFactory:
    """Factory for creating Wan inference pipelines."""
    
    def __init__(self, model_config: Optional[WanModelConfig] = None):
        self.model_config = model_config or WanModelConfig()
    
    def create_pipeline(
        self,
        job_id: str,
        session_id: str,
        experience_id: str,
        capture_ref: str,
        generation_config: WanGenerationConfig,
    ) -> WanInferencePipeline:
        return WanInferencePipeline(
            model_config=self.model_config,
            generation_config=generation_config,
            job_id=job_id,
            session_id=session_id,
            experience_id=experience_id,
            capture_ref=capture_ref,
        )
    
    def create_pipeline_from_request(
        self,
        job_id: str,
        session_id: str,
        experience_id: str,
        capture_ref: str,
        provider_input: Any,  # ProviderInput from base
    ) -> WanInferencePipeline:
        """Create pipeline from provider input."""
        # Build generation config from provider input
        gen_config = WanGenerationConfig(
            prompt="",  # Will be filled by ExperienceConfigurationStage
            negative_prompt="",
            num_inference_steps=provider_input.num_inference_steps or 28,
            guidance_scale=provider_input.guidance_scale or 7.5,
            motion_bucket_id=provider_input.motion_bucket_id or 180,
            seed=provider_input.fixed_seed,
            fps=provider_input.fps or 12,
            duration_sec=provider_input.duration_sec or 4.0,
            resolution=f"{provider_input.width}x{provider_input.height}" if hasattr(provider_input, 'width') else "720x1280",
            seed_policy=provider_input.seed_policy or "visitor_derived",
            fixed_seed=provider_input.fixed_seed,
            strength=provider_input.strength or 0.7,
        )
        
        return self.create_pipeline(
            job_id=job_id,
            session_id=session_id,
            experience_id=experience_id,
            capture_ref=capture_ref,
            generation_config=gen_config,
        )


# ============================================================
# Standalone Inference Script
# ============================================================

async def run_standalone_inference(
    capture_image_path: str,
    experience_id: str,
    output_path: str,
    model_config: Optional[WanModelConfig] = None,
    generation_config: Optional[WanGenerationConfig] = None,
    progress_callback: Optional[Callable[[float, str], None]] = None,
) -> dict:
    """
    Standalone inference script for testing without web app.
    
    Usage:
        python -m aura_backend.inference.wan_pipeline \
            --image path/to/image.jpg \
            --experience aurora \
            --output output.mp4
    """
    from .wan_loader import get_wan_loader
    from .wan_config import WanModelConfig, WanGenerationConfig
    
    model_config = model_config or WanModelConfig()
    generation_config = generation_config or WanGenerationConfig()
    
    # Load model
    loader = get_wan_loader(model_config)
    components = loader.load()
    
    # Load image
    image = Image.open(capture_image_path).convert("RGB")
    
    # Build prompt
    from .wan_config import build_wan_prompt
    prompt = build_wan_prompt(experience_id, "a person")
    
    # Generate
    pipeline = get_wan_loader(model_config).get_pipeline()
    
    # ... inference code ...
    pass


# ============================================================
# Exports
# ============================================================

__all__ = [
    "PipelineContext",
    "PipelineStage",
    "PipelineError",
    "PipelineError",
    "InputValidationStage",
    "ImagePreprocessingStage",
    "ReferencePreparationStage",
    "ExperienceConfigurationStage",
    "ModelLoadingStage",
    "InferenceStage",
    "PostProcessingStage",
    "VideoEncodingStage",
    "OutputValidationStage",
    "CleanupStage",
    "WanInferencePipeline",
    "WanPipelineFactory",
    "PipelineError",
    "run_standalone_inference",
    "WanPipelineFactory",
]