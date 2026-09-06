"""
Wan 2.1 Model Loader with Caching and Warmup.

This module handles model loading, caching, and warmup for the Wan 2.1 I2V model.
It handles model sharding, offloading, and VRAM optimization.
"""

from __future__ import annotations

import gc
import os
import time
import threading
import warnings
from contextlib import contextmanager
from dataclasses import dataclass
from typing import Any, Optional

try:
    import torch  # type: ignore[import-not-found]
    _TORCH_AVAILABLE = True
except ImportError:  # pragma: no cover - CPU-only / CI without GPU extras
    torch = None  # type: ignore[assignment]
    _TORCH_AVAILABLE = False

from .wan_config import (
    WanModelConfig,
    WanGenerationConfig,
    WanModelConfig,
    WanModelVariant,
    WanPrecision,
    WanSchedulerType,
    DEFAULT_MODEL_REPO,
    DEFAULT_NEGATIVE_PROMPT,
    validate_generation_config,
    DEFAULT_NEGATIVE_PROMPT,
)

# Suppress some verbose warnings
os.environ.setdefault("TOKENIZERS_PARALLELISM", "false")
warnings.filterwarnings("ignore", category=FutureWarning)
warnings.filterwarnings("ignore", category=UserWarning, module="diffusers")

# Lazy imports to avoid import-time overhead
_torch = torch


def _require_torch() -> None:
    if not _TORCH_AVAILABLE or torch is None:
        raise ImportError(
            "wan-local provider requires GPU extras: pip install -e '.[gpu]'"
        )


def place_pipeline_on_device(
    pipeline: Any, *, enable_offload: bool, offload_to_cpu: bool, device: Any
) -> Any:
    """Place a diffusers pipeline for inference without OOMing the move itself.

    - model CPU offload owns placement: enable it directly, never .to() first.
    - otherwise move wholesale with .to(device), then optionally sequential offload.
    """
    if enable_offload:
        pipeline.enable_model_cpu_offload()
        return pipeline
    moved = pipeline.to(device)
    if offload_to_cpu:
        moved.enable_sequential_cpu_offload()
    return moved


@dataclass
class ModelComponents:
    """Loaded model components."""
    transformer: Any = None
    vae: Any = None
    text_encoder: Any = None
    tokenizer: Any = None
    scheduler: Any = None
    image_encoder: Any = None
    image_processor: Any = None
    pipeline: Any = None
    config: "WanPipelineConfig" = None


@dataclass
class WanPipelineConfig:
    """Pipeline configuration for inference."""
    model_config: "WanModelConfig"
    device: str
    dtype: torch.dtype
    transformer: Any = None
    vae: Any = None
    text_encoder: Any = None
    tokenizer: Any = None
    scheduler: Any = None
    image_encoder: Any = None
    image_processor: Any = None


class WanModelLoader:
    """
    Thread-safe model loader with caching and warmup.
    
    Handles:
    - Model loading from local path or Hugging Face Hub
    - Precision management (fp16/bf16/fp32)
    - Model offloading (CPU/GPU)
    - VAE tiling for memory efficiency
    - xFormers / Flash Attention enablement
    - Model compilation (torch.compile)
    - Warmup runs for JIT compilation
    - Thread-safe singleton access
    """
    
    _instance: Optional["WanModelLoader"] = None
    _lock = threading.Lock()
    _loaded: bool = False
    _warm: bool = False
    
    def __new__(cls, config: Optional["WanModelConfig"] = None):
        if cls._instance is None:
            with cls._lock:
                if cls._instance is None:
                    cls._instance = super().__new__(cls)
                    cls._instance._initialized = False
        return cls._instance
    
    def __init__(self, config: Optional["WanModelConfig"] = None):
        if self._initialized:
            return
        self._initialized = True
        self.config = config or WanModelConfig()
        self._components: Optional[ModelComponents] = None
        self._pipeline: Optional[Any] = None
        self._load_lock = threading.Lock()
        self._load_time: Optional[float] = None
        self._device: Optional[torch.device] = None
        self._dtype: Optional[torch.dtype] = None
        
    @property
    def is_loaded(self) -> bool:
        return self._loaded
    
    @property
    def is_warm(self) -> bool:
        return self._warm
    
    @property
    def device(self) -> Any:
        _require_torch()
        if self._device is None:
            assert torch is not None
            self._device = torch.device(self.config.device if torch.cuda.is_available() else "cpu")
        return self._device
    
    @property
    def dtype(self) -> Any:
        _require_torch()
        if self._dtype is None:
            assert torch is not None
            precision_map = {
                "fp16": torch.float16,
                "bf16": torch.bfloat16,
                "fp32": torch.float32,
            }
            self._dtype = precision_map.get(self.config.precision.value, torch.bfloat16)
        return self._dtype
    
    def load(self, force_reload: bool = False) -> ModelComponents:
        """
        Load model components.
        
        Args:
            force_reload: If True, reload even if already loaded.
            
        Returns:
            Loaded ModelComponents.
            
        Raises:
            RuntimeError: If model loading fails.
        """
        if self._loaded and not force_reload:
            return self._components
        
        with self._load_lock:
            if self._loaded and not force_reload:
                return self._components
            
            start_time = time.time()
            
            try:
                components = self._load_components_with_oom_retry()
                self._components = components
                self._loaded = True
                self._load_time = time.time() - start_time
                
                # Warm up if configured
                if self.config.compile_transformer or self.config.compile_vae:
                    self.warmup()
                
                return components
                
            except torch.cuda.OutOfMemoryError as e:
                self._handle_oom("load")
                raise RuntimeError(f"Failed to load Wan model: OOM - {e}") from e
            except Exception as e:
                self._loaded = False
                self._components = None
                raise RuntimeError(f"Failed to load Wan model: {e}") from e
    
    def _load_components_with_oom_retry(self) -> ModelComponents:
        """Load components with OOM retry logic."""
        max_retries = 3
        retry_delay = 1.0
        
        for attempt in range(max_retries):
            try:
                return self._load_components()
            except torch.cuda.OutOfMemoryError as e:
                if attempt < max_retries - 1:
                    print(f"OOM on load attempt {attempt + 1}/{max_retries}, retrying...")
                    self._handle_oom(f"load_attempt_{attempt + 1}")
                    time.sleep(retry_delay)
                    retry_delay *= 2
                else:
                    raise
    
    def _load_components(self) -> ModelComponents:
        """Load all model components."""
        from diffusers import (
            WanImageToVideoPipeline,
            WanTransformer3DModel,
            AutoencoderKLWan,
            UniPCMultistepScheduler,
        )
        from transformers import CLIPImageProcessor, CLIPVisionModel
        # Wan 2.1 text encoder is UMT5 (model_type "umt5"), not plain T5.
        try:
            from transformers import UMT5EncoderModel as _TextEncoderClass
        except ImportError:
            from transformers import T5EncoderModel as _TextEncoderClass
        from transformers import T5TokenizerFast

        # Determine model repo
        model_repo = self.config.local_model_path or DEFAULT_MODEL_REPO

        # Small pods: stream weights with accelerate device_map + disk
        # offload so RAM never holds them all (defined up-front: the text
        # encoder block below runs before the transformer block).
        _disk_offload = bool(self.config.offload_to_cpu)
        _offload_folder = os.environ.get("AURA_WAN_OFFLOAD_FOLDER", "/workspace/.offload")
        if _disk_offload:
            try:
                os.makedirs(_offload_folder, exist_ok=True)
            except Exception:
                import tempfile as _tf

                _offload_folder = _tf.mkdtemp(prefix="aura_offload_")

        # Load tokenizer and text encoder first (smallest)
        tokenizer = T5TokenizerFast.from_pretrained(
            model_repo,
            subfolder="tokenizer",
        )

        if _disk_offload:
            text_encoder = _TextEncoderClass.from_pretrained(
                model_repo,
                subfolder="text_encoder",
                torch_dtype=self.dtype,
                device_map="auto",
                max_memory={0: "1GiB", "cpu": "10GiB"},
                offload_folder=_offload_folder,
                offload_state_dict=True,
                low_cpu_mem_usage=True,
            )
        else:
            text_encoder = _TextEncoderClass.from_pretrained(
                model_repo,
                subfolder="text_encoder",
                torch_dtype=self.dtype,
                low_cpu_mem_usage=True,
            )
        
        # Load VAE
        vae = AutoencoderKLWan.from_pretrained(
            model_repo,
            subfolder="vae",
            torch_dtype=torch.float32,  # VAE typically runs in FP32
            low_cpu_mem_usage=True,
        )
        
        # Enable VAE tiling for memory efficiency (method name varies by
        # diffusers version; slicing below is the guaranteed fallback).
        if self.config.enable_vae_tiling:
            if hasattr(vae, "enable_tiling"):
                try:
                    vae.enable_tiling()
                except Exception:
                    pass
            if hasattr(vae, "tile_size"):
                try:
                    vae.tile_size = self.config.vae_tile_size
                except Exception:
                    pass
        
        # Load transformer (largest component, ~65GB on disk).
        # _disk_offload/_offload_folder were set up at the top of this
        # function (the text-encoder block above runs first).
        if _disk_offload:
            transformer = WanTransformer3DModel.from_pretrained(
                model_repo,
                subfolder="transformer",
                torch_dtype=self.dtype,
                device_map="auto",
                max_memory={0: "11GiB", "cpu": "12GiB"},
                offload_folder=_offload_folder,
                offload_state_dict=True,
                low_cpu_mem_usage=True,
            )
        else:
            transformer = WanTransformer3DModel.from_pretrained(
                model_repo,
                subfolder="transformer",
                torch_dtype=self.dtype,
                low_cpu_mem_usage=True,
            )
        
        # Load scheduler (from_pretrained resolves the actual class
        # from the repo's scheduler_config.json)
        scheduler = UniPCMultistepScheduler.from_pretrained(
            model_repo,
            subfolder="scheduler",
        )

        # Load image conditioning components (I2V needs both; ~1.3GB total)
        image_encoder = CLIPVisionModel.from_pretrained(
            model_repo,
            subfolder="image_encoder",
        )
        image_processor = CLIPImageProcessor.from_pretrained(
            model_repo,
            subfolder="image_processor",
        )

        # Apply optimizations
        self._apply_optimizations(text_encoder, vae, transformer)

        # Create pipeline (image-to-video: takes image= as first input)
        pipeline = WanImageToVideoPipeline(
            tokenizer=tokenizer,
            text_encoder=text_encoder,
            image_encoder=image_encoder,
            image_processor=image_processor,
            transformer=transformer,
            vae=vae,
            scheduler=scheduler,
        )
        
        if _disk_offload:
            # Already dispatched across CUDA/CPU/disk by accelerate; .to()
            # and the offload toggles would conflict, so only slice the VAE.
            try:
                pipeline.vae.enable_slicing()
            except Exception:
                pass
        else:
            # Place on device (offload strategies own placement; a blind
            # .to("cuda") of a ~30GB model onto a 24GB card OOMs first).
            pipeline = place_pipeline_on_device(
                pipeline,
                enable_offload=self.config.enable_offload,
                offload_to_cpu=self.config.offload_to_cpu,
                device=self.device,
            )

            # Enable VAE slicing for memory efficiency
            pipeline.vae.enable_slicing()
        
        return ModelComponents(
            transformer=transformer,
            vae=vae,
            text_encoder=text_encoder,
            tokenizer=tokenizer,
            scheduler=scheduler,
            image_encoder=image_encoder,
            image_processor=image_processor,
            pipeline=pipeline,
            config=self._create_pipeline_config(),
        )
    
    def _apply_optimizations(
        self,
        text_encoder: Any,
        vae: Any,
        transformer: Any,
    ) -> None:
        """Apply various optimizations to model components."""
        
        # Enable xFormers memory efficient attention
        if self.config.enable_xformers:
            try:
                text_encoder.enable_xformers_memory_efficient_attention()
            except Exception:
                pass  # xFormers may not be available
            
            try:
                vae.enable_xformers_memory_efficient_attention()
            except Exception:
                pass
            
            try:
                transformer.enable_xformers_memory_efficient_attention()
            except Exception:
                pass
        
        # Enable Flash Attention 2 if available
        if self.config.enable_flash_attention:
            try:
                from flash_attn import flash_attn_func
                # Flash Attention 2 is automatically used by transformers
                # when available and model supports it
            except ImportError:
                pass
        
        # Compile models if requested
        if self.config.compile_transformer:
            import torch._dynamo
            torch._dynamo.reset()
            # Compile transformer (most compute-intensive)
            # Note: This may take time on first run
        
        if self.config.compile_vae:
            import torch._dynamo
            # Compile VAE for faster encoding/decoding
    
    def _create_pipeline_config(self) -> "WanPipelineConfig":
        return WanPipelineConfig(
            model_config=self.config,
            device=self.device,
            dtype=self.dtype,
            transformer=self._components.transformer if self._components else None,
            vae=self._components.vae if self._components else None,
            text_encoder=self._components.text_encoder if self._components else None,
            tokenizer=self._components.tokenizer if self._components else None,
            scheduler=self._components.scheduler if self._components else None,
        )
    
    def warmup(self, num_warmup_steps: int = 2) -> None:
        """
        Warm up the model with dummy inferences.
        
        This triggers:
        - CUDA kernel compilation/caching
        - Memory allocation patterns
        - JIT compilation (if using torch.compile)
        
        Args:
            num_warmup_steps: Number of warmup iterations.
        """
        if self._warm:
            return
        
        if not self._loaded:
            self.load()
        
        print("Warming up Wan model...")
        start = time.time()
        
        try:
            pipeline = self._components.pipeline
            
            # Create dummy input
            dummy_image = torch.randn(
                1, 3, 720, 1280,
                device=self.device,
                dtype=self.dtype
            )
            
            dummy_prompt = "A test prompt for warmup"
            
            for i in range(num_warmup_steps):
                with torch.inference_mode():
                    _ = pipeline(
                        prompt="warmup",
                        image=dummy_image,
                        num_inference_steps=1,
                        guidance_scale=1.0,
                        num_frames=4,
                        height=720,
                        width=1280,
                    )
                torch.cuda.synchronize()
            
            self._warm = True
            elapsed = time.time() - start
            print(f"Warmup completed in {elapsed:.2f}s")
            
        except Exception as e:
            print(f"Warmup failed (non-fatal): {e}")
    
    def get_pipeline(self) -> Any:
        """Get the loaded pipeline."""
        if not self._loaded:
            self.load()
        return self._components.pipeline
    
    def unload(self) -> None:
        """Unload model and free VRAM."""
        with self._load_lock:
            if self._components:
                # Move to CPU and delete
                if self._components.pipeline:
                    self._components.pipeline.to("cpu")
                if self._components.transformer:
                    self._components.transformer.to("cpu")
                if self._components.vae:
                    self._components.vae.to("cpu")
                if self._components.text_encoder:
                    self._components.text_encoder.to("cpu")
                
                # Clear references
                self._components = None
                self._pipeline = None
                self._loaded = False
                self._warm = False
                
                # Force garbage collection
                gc.collect()
                torch.cuda.empty_cache()
                
                print("Model unloaded, VRAM freed")
    
    def _handle_oom(self, context: str) -> None:
        """Handle OOM by clearing cache and trying to free memory."""
        print(f"OOM detected during {context}, attempting recovery...")
        gc.collect()
        if torch.cuda.is_available():
            torch.cuda.empty_cache()
            torch.cuda.ipc_collect()
            torch.cuda.synchronize()
        # Force garbage collection again
        gc.collect()
        # Log current memory state
        stats = get_vram_usage()
        if stats.get("available"):
            print(f"VRAM after OOM recovery: "
                  f"Allocated: {stats['allocated_gb']:.2f}GB, "
                  f"Reserved: {stats['reserved_gb']:.2f}GB")
    
    def get_memory_stats(self) -> dict:
        """Get detailed memory statistics."""
        return get_vram_usage()
    
    def is_healthy(self) -> bool:
        """Check if loader is healthy."""
        return self._loaded and self._components is not None


# Global loader instance
_global_loader: Optional[WanModelLoader] = None
_loader_lock = threading.Lock()


def get_wan_loader(config: Optional[WanModelConfig] = None) -> WanModelLoader:
    """Get or create the global Wan model loader."""
    global _global_loader
    with _loader_lock:
        if _global_loader is None:
            _global_loader = WanModelLoader(config)
        return _global_loader


def set_global_loader(loader: WanModelLoader) -> None:
    """Override the global loader (for testing)."""
    global _global_loader
    _global_loader = loader


@contextmanager
def model_context(config: Optional[WanModelConfig] = None):
    """Context manager for model lifecycle."""
    loader = get_wan_loader(config)
    try:
        loader.load()
        yield loader
    finally:
        loader.unload()


def get_device() -> torch.device:
    """Get the default device."""
    return torch.device("cuda" if torch.cuda.is_available() else "cpu")


def get_dtype(precision: str = "bf16") -> torch.dtype:
    """Get torch dtype from precision string."""
    return {
        "fp16": torch.float16,
        "bf16": torch.bfloat16,
        "fp32": torch.float32,
    }.get(precision, torch.bfloat16)


@contextmanager
def inference_mode():
    """Context manager for inference mode with automatic cleanup."""
    with torch.inference_mode():
        try:
            yield
        finally:
            gc.collect()
            if torch.cuda.is_available():
                torch.cuda.empty_cache()


def clear_cuda_cache():
    """Clear CUDA cache and run garbage collection."""
    gc.collect()
    if torch.cuda.is_available():
        torch.cuda.empty_cache()
        torch.cuda.ipc_collect()


def get_vram_usage() -> dict:
    """Get current VRAM usage stats."""
    if not torch.cuda.is_available():
        return {"available": False}
    
    return {
        "allocated_gb": torch.cuda.memory_allocated() / 1024**3,
        "reserved_gb": torch.cuda.memory_reserved() / 1024**3,
        "max_allocated_gb": torch.cuda.max_memory_allocated() / 1024**3,
        "max_reserved_gb": torch.cuda.max_memory_reserved() / 1024**3,
        "total_gb": torch.cuda.get_device_properties(0).total_memory / 1024**3,
    }


def print_vram_usage(label: str = "VRAM"):
    """Print current VRAM usage."""
    stats = get_vram_usage()
    if stats.get("available"):
        print(
            f"{label}: "
            f"Allocated: {stats['allocated_gb']:.2f}GB, "
            f"Reserved: {stats['reserved_gb']:.2f}GB, "
            f"Max: {stats['max_allocated_gb']:.2f}GB / {stats['total_gb']:.2f}GB"
        )
    else:
        print(f"{label}: CUDA not available")