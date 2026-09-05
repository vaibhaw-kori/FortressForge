"""
Wan 2.1 14B Model Configuration and Constants.

This module defines all model-specific constants, default parameters,
and configuration schemas for the Wan 2.1 14B I2V model.
"""

from __future__ import annotations

from dataclasses import dataclass, field
from enum import Enum
from typing import Any


class WanModelVariant(str, Enum):
    """Supported Wan 2.1 model variants."""
    WAN_2_1_I2V_14B_720P = "wan2.1-i2v-14b-720p"
    WAN_2_1_I2V_14B_480P = "wan2.1-i2v-14b-480p"
    WAN_2_1_I2V_1_3B_480P = "wan2.1-i2v-1.3b-480p"
    WAN_2_1_T2V_14B = "wan2.1-t2v-14b"


class WanPrecision(str, Enum):
    """Supported precision modes."""
    FP16 = "fp16"
    BF16 = "bf16"
    FP32 = "fp32"


class WanSchedulerType(str, Enum):
    """Supported schedulers for Wan."""
    UNIPC = "unipc"
    DDIM = "ddim"
    DPM_SOLVER = "dpm_solver"
    EULER_A = "euler_ancestral"


# Default model repository on Hugging Face.
# Verified 2026-09: the 1.3B line is T2V-only upstream (no image input), so
# image-to-video MUST use a 14B I2V repo. 480P fits 16GB via sequential
# CPU offload; 720P needs an A6000 (48GB).
DEFAULT_MODEL_REPO = "Wan-AI/Wan2.1-I2V-14B-480P"
# 720P repo for A6000: "Wan-AI/Wan2.1-I2V-14B-720P"

# Model subdirectories
MODEL_SUBDIRS = {
    "transformer": "transformer",
    "vae": "vae",
    "text_encoder": "text_encoder",
    "scheduler": "scheduler",
}

# Default generation parameters for Wan 2.1 I2V — 1.3B 480P profile (16GB)
DEFAULT_WAN_PARAMS = {
    "num_inference_steps": 24,
    "guidance_scale": 7.0,
    "motion_bucket_id": 160,
    "seed_policy": "visitor_derived",
    "fps": 12,
    "duration_sec": 4.0,
    "resolution": "480x832",
    "aspect_ratio": "9:16",
    "num_frames": 48,  # 4 seconds @ 12fps
    "guidance_scale_min": 1.0,
    "guidance_scale_max": 20.0,
    "num_inference_steps_min": 10,
    "num_inference_steps_max": 50,
}

# Resolution presets
RESOLUTION_PRESETS = {
    "720x1280": (720, 1280),   # 9:16 portrait
    "1280x720": (1280, 720),   # 16:9 landscape
    "480x832": (480, 832),     # 9:16 low-res
    "832x480": (832, 480),     # 16:9 low-res
    "1080x1920": (1080, 1920), # 9:16 full HD
    "1920x1080": (1920, 1080), # 16:9 full HD
}

# Maximum frames per resolution (memory constraints)
MAX_FRAMES_BY_RESOLUTION = {
    (720, 1280): 81,   # 4s @ 12fps = 48, but model supports up to 81
    (480, 832): 81,
    (1080, 1920): 48,  # Higher res = fewer frames due to VRAM
    (1920, 1080): 48,
}


@dataclass(frozen=True)
class WanModelConfig:
    """Immutable model configuration — 14B 480P I2V (sequential offload on 16GB)."""
    variant: WanModelVariant = WanModelVariant.WAN_2_1_I2V_14B_480P
    precision: WanPrecision = WanPrecision.BF16
    scheduler_type: WanSchedulerType = WanSchedulerType.UNIPC
    model_repo: str = DEFAULT_MODEL_REPO
    local_model_path: str | None = None
    enable_offload: bool = False
    offload_to_cpu: bool = False
    enable_vae_tiling: bool = True
    vae_tile_size: int = 384
    enable_xformers: bool = True
    enable_flash_attention: bool = True
    compile_transformer: bool = False
    compile_vae: bool = False
    device: str = "cuda"
    dtype: str = "bfloat16"


@dataclass
class WanGenerationConfig:
    """Runtime generation configuration (mutable per-request)."""
    prompt: str = ""
    negative_prompt: str = ""
    num_inference_steps: int = 28
    guidance_scale: float = 7.5
    motion_bucket_id: int = 180
    seed: int | None = None
    fps: int = 12
    duration_sec: float = 4.0
    width: int = 720
    height: int = 1280
    num_frames: int = 48
    guidance_scale_min: float = 1.0
    guidance_scale_max: float = 20.0
    num_inference_steps_min: int = 10
    num_inference_steps_max: int = 50
    seed_policy: str = "visitor_derived"  # "visitor_derived", "random", "fixed"
    fixed_seed: int | None = None
    strength: float = 0.7  # denoising strength for img2vid
    motion_scale: float = 1.0
    enable_preview: bool = False
    preview_every_n_steps: int = 5

    def __post_init__(self):
        # NOTE: do NOT clamp here — validation is handled explicitly by
        # validate_generation_config() so callers can detect bad input.
        # Only derive num_frames from fps*duration when the caller left
        # num_frames at its default (48) but customized fps/duration.
        # If the caller explicitly set num_frames, preserve it so
        # validation can reject out-of-range values.
        default_frames = 48
        fps_custom = (self.fps != 12)
        dur_custom = (self.duration_sec != 4.0)
        if self.num_frames == default_frames and (fps_custom or dur_custom):
            try:
                self.num_frames = int(self.fps * self.duration_sec)
            except Exception:
                pass

    def to_dict(self) -> dict:
        return {
            "prompt": self.prompt,
            "negative_prompt": self.negative_prompt,
            "num_inference_steps": self.num_inference_steps,
            "guidance_scale": self.guidance_scale,
            "motion_bucket_id": self.motion_bucket_id,
            "seed": self.seed,
            "fps": self.fps,
            "duration_sec": self.duration_sec,
            "width": self.width,
            "height": self.height,
            "num_frames": self.num_frames,
            "seed_policy": self.seed_policy,
            "fixed_seed": self.fixed_seed,
            "strength": self.strength,
            "motion_scale": self.motion_scale,
        }


# Default negative prompt for Wan I2V
DEFAULT_NEGATIVE_PROMPT = (
    "blurry, low quality, distorted, deformed, ugly, bad anatomy, "
    "extra limbs, missing limbs, floating limbs, disconnected limbs, "
    "mutation, mutated, ugly, disgusting, blurry, lowres, pixelated, "
    "watermark, text, title, logo, signature, username, artist name, "
    "glitch, artifacts, jpeg artifacts, compression artifacts, "
    "oversaturated, oversharpened, oversmoothed, plastic, waxy, "
    "deformed face, asymmetric face, crossed eyes, uneven eyes, "
    "bad proportions, malformed hands, extra fingers, missing fingers, "
    "fused fingers, too many fingers, claw, mutated hands, "
    "bad anatomy, ugly, duplicate, morbid, mutilated, "
    "poorly drawn face, poorly drawn hands, poorly drawn feet, "
    "mutation, deformed, ugly, bad anatomy, blurry, "
    "low quality, worst quality, lowres, bad composition, "
    "amputation, missing body parts, extra body parts, "
    "floating body parts, disconnected body parts, "
    "malformed body, long neck, missing arms, missing legs, "
    "extra arms, extra legs, fused limbs, too many limbs, "
    "missing limbs, bad anatomy, ugly, deformed, blurry, "
    "watermark, text, signature, logo, username, blurry, low quality"
)

# Experience-specific prompt templates (to be customized per theme)
EXPERIENCE_PROMPT_TEMPLATES = {
    "aurora": (
        "Cinematic portrait of {visitor} surrounded by flowing neon aurora ribbons, "
        "arctic sky background, soft volumetric light, ethereal particles, "
        "gentle camera dolly-in motion. High production value, 35mm film look, "
        "photorealistic, 8k resolution, cinematic lighting, "
        "volumetric fog, aurora borealis colors, magical atmosphere"
    ),
    "mirage": (
        "Cinematic portrait of {visitor} beside a shimmering desert oasis at golden hour, "
        "heat haze, golden dust particles suspended in warm light, "
        "subtle camera orbit. Luxury perfume-ad aesthetic, soft bokeh, "
        "cinematic lighting, golden hour, heat distortion, "
        "particle effects, dreamy atmosphere, photorealistic"
    ),
    "pulse": (
        "Bold kinetic portrait of {visitor} with high-contrast geometric waves, "
        "magenta and white color blocks, sharp motion synced to a beat, "
        "fast parallax camera move. Music video aesthetic, "
        "high contrast, neon colors, dynamic motion, "
        "glitch art style, cyberpunk aesthetic, sharp edges"
    ),
    "driftwood": (
        "Quiet cinematic portrait of {visitor} on a moonlit shoreline. "
        "Long exposure water, soft moonlight, gentle drift. "
        "Contemplative, painterly, slow camera dolly. "
        "Moonlight, calm water, serene atmosphere, "
        "cinematic, peaceful, meditative, photorealistic"
    ),
}

def get_experience_prompt(experience_id: str, visitor_description: str = "a person") -> str:
    """Get the prompt template for an experience, formatted with visitor description."""
    template = EXPERIENCE_PROMPT_TEMPLATES.get(experience_id, "")
    if not template:
        # Generic fallback
        return f"Cinematic portrait of {visitor_description} in a {experience_id} theme, high quality, cinematic"
    return template.format(visitor=visitor_description)

def build_wan_prompt(
    experience_id: str,
    visitor_description: str = "a person",
    custom_prompt: str | None = None,
) -> str:
    """Build the complete prompt for Wan I2V."""
    if custom_prompt:
        return custom_prompt
    return get_experience_prompt(experience_id, visitor_description)


def validate_generation_config(config: WanGenerationConfig) -> tuple[bool, list[str]]:
    """Validate generation config and return (is_valid, errors)."""
    errors = []
    
    if not config.prompt or len(config.prompt.strip()) < 5:
        errors.append("Prompt too short (min 5 characters)")
    
    if config.num_inference_steps < 10 or config.num_inference_steps > 50:
        errors.append("num_inference_steps must be between 10 and 50")
    
    if config.guidance_scale < 1.0 or config.guidance_scale > 20.0:
        errors.append("guidance_scale must be between 1.0 and 20.0")
    
    if config.fps < 1 or config.fps > 30:
        errors.append("fps must be between 1 and 30")
    
    if config.duration_sec < 0.5 or config.duration_sec > 10.0:
        errors.append("duration_sec must be between 0.5 and 10.0")
    
    if config.width % 8 != 0 or config.height % 8 != 0:
        errors.append("Width and height must be multiples of 8 (VAE constraint)")
    
    if config.width * config.height > 1920 * 1080:
        errors.append("Resolution too high (max 1920x1080)")
    
    if config.num_frames < 8 or config.num_frames > 81:
        errors.append("num_frames must be between 8 and 81")
    
    if config.strength < 0.0 or config.strength > 1.0:
        errors.append("strength must be between 0.0 and 1.0")
    
    if config.motion_bucket_id < 1 or config.motion_bucket_id > 255:
        errors.append("motion_bucket_id must be between 1 and 255")
    
    return len(errors) == 0, errors