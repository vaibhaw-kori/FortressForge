"""
Shared GenerationQualityConfig — common stability layer for all themes.

Aurora / Mirage / Pulse converge here. Theme layer controls style/environment,
quality layer controls identity/anatomy/temporal.

This is the single place to tune shared quality without scattering if pulse.
"""

from __future__ import annotations

from dataclasses import dataclass


@dataclass(frozen=True)
class GenerationQualityConfig:
    """
    Shared quality knobs — applied to EVERY theme before inference.

    Baseline (current fast demo): 720x1280 8 steps, strength 0.60, guidance 7.0, motion 150
    Proposed stable: 480x832 native, 16 steps, strength 0.52, guidance 6.8, motion 120

    Phase 1-7 controlled experiments vary these one at a time.
    """

    # Model-native resolution for WAN 2.1 14B 480P-Diffusers.
    # 480x832 = 9:16 portrait, 832%8==0, 480%8==0, <=1920*1080, VAE tile 384 compatible.
    # Using 720x1280 on 480P weights forces 1.78× upscale of 405×720 crop → blur → hallucinated anatomy.
    # 480x832 crop is 415×720 → 480×832 = 1.15× upscale, minimal blur, max face detail.
    width: int = 480
    height: int = 832

    # Sampling — 8 is fast demo, 16 is premium quality point for controlled test.
    num_inference_steps: int = 16

    # Conditioning
    guidance_scale: float = 6.8  # ↓7.5 reduces prompt overpowering image
    motion_bucket_id: int = 120  # ↓150-180 reduces deformation, keeps controlled motion

    # Reference strength — verify in wan_pipeline.py: strength is denoising strength
    # where lower = stronger reference preservation in diffusers I2V (image latent blended
    # with noise: strength 0.52 = 52% noise, 48% image). We use 0.52 to keep identity.
    strength: float = 0.52
    motion_strength: float = 0.55  # kept moderate, not frozen

    # Shared identity constraints appended to every negative prompt and injected into positive.
    identity_positive_suffix: str = (
        " same person, same face, same clothing, preserve facial identity, "
        "preserve body proportions, stable anatomy, consistent clothing, "
        "coherent subject throughout sequence, no deformation"
    )
    identity_negative_add: str = (
        "deformed, extra limbs, missing limbs, fused limbs, bad anatomy, "
        "face morphing, body morphing, clothing changing, unstable geometry, "
        "excessive cropping, face cropped, head cropped, dark, near-black, flicker"
    )


# Baseline vs experiment presets for controlled testing
BASELINE = GenerationQualityConfig(
    width=720, height=1280, num_inference_steps=8, guidance_scale=7.0, motion_bucket_id=150, strength=0.60
)
TEST_A = GenerationQualityConfig(
    width=480, height=832, num_inference_steps=16, guidance_scale=7.0, motion_bucket_id=120, strength=0.60
)
TEST_B = GenerationQualityConfig(
    width=480, height=832, num_inference_steps=16, guidance_scale=6.8, motion_bucket_id=120, strength=0.52
)
TEST_C = GenerationQualityConfig(
    width=480, height=832, num_inference_steps=20, guidance_scale=6.8, motion_bucket_id=120, strength=0.52
)
