#!/usr/bin/env python
"""
Standalone Wan 2.1 Inference Script.

This script can be run independently to test the Wan 2.1 inference pipeline
without the web application.

Usage:
    python -m aura_backend.inference.wan_standalone \
        --image path/to/image.jpg \
        --experience aurora \
        --output output.mp4 \
        --steps 28 \
        --guidance 7.5

Environment variables:
    AURA_WAN_MODEL_VARIANT - Model variant (default: wan2.1-i2v-14b-720p)
    AURA_WAN_PRECISION - Precision (fp16, bf16, fp32)
    AURA_WAN_MODEL_REPO - Hugging Face model repo
    AURA_WAN_LOCAL_PATH - Local model path (optional)
    AURA_WAN_PRECISION - bf16 (default), fp16, or fp32
"""

from __future__ import annotations

import argparse
import asyncio
import os
import shutil
import sys
import uuid
from pathlib import Path

# Add parent directory to path for imports
sys.path.insert(0, str(Path(__file__).parent.parent.parent.parent))

import torch
from PIL import Image

from aura_backend.inference.wan_config import (
    WanModelConfig,
    WanGenerationConfig,
    WanModelVariant,
    WanPrecision,
    WanSchedulerType,
    build_wan_prompt,
    DEFAULT_NEGATIVE_PROMPT,
)
from aura_backend.inference.wan_loader import get_wan_loader, WanModelLoader
from aura_backend.inference.wan_pipeline import WanInferencePipeline, WanPipelineFactory
from aura_backend.inference.wan_loader import get_wan_loader


async def run_inference(
    image_path: str,
    experience_id: str,
    output_path: str,
    model_config: WanModelConfig,
    generation_config: WanGenerationConfig,
    progress_callback=None,
) -> dict:
    """Run the inference pipeline."""
    
    # Load model
    print(f"Loading model: {model_config.variant.value}...")
    loader = WanModelLoader(model_config)
    components = loader.load()
    print("Model loaded successfully")
    
    # Load and preprocess image
    from PIL import Image
    image = Image.open(image_path).convert("RGB")
    print(f"Loaded image: {image.size}")
    
    # Build prompt
    prompt = build_wan_prompt(experience_id, "a person")
    print(f"Prompt: {prompt[:100]}...")
    
    # Create generation config with prompt
    gen_config = WanGenerationConfig(
        prompt=prompt,
        negative_prompt="",
        num_inference_steps=generation_config.num_inference_steps,
        guidance_scale=generation_config.guidance_scale,
        motion_bucket_id=generation_config.motion_bucket_id,
        seed=generation_config.seed,
        fps=generation_config.fps,
        duration_sec=generation_config.duration_sec,
        resolution=generation_config.resolution,
        aspect_ratio=generation_config.aspect_ratio,
    )
    
    # Create pipeline
    factory = WanPipelineFactory(model_config)
    pipeline = WanInferencePipeline(
        model_config=model_config,
        generation_config=gen_config,
        job_id="standalone-" + str(uuid.uuid4().hex[:8]),
        session_id="standalone-session",
        experience_id=experience_id,
        capture_ref="local:" + image_path,
    )
    
    # Override pipeline with our loaded components
    from aura_backend.inference.wan_loader import get_wan_loader
    loader = get_wan_loader(model_config)
    components = loader.load()
    
    # We need to inject our loaded components into the pipeline
    pipeline = WanInferencePipeline(
        model_config=model_config,
        generation_config=gen_config,
        job_id="standalone-" + str(uuid.uuid4().hex[:8]),
        session_id="standalone-session",
        experience_id=experience_id,
        capture_ref="local:" + image_path,
    )
    pipeline.pipeline = get_wan_loader(model_config).get_pipeline()
    
    # Run pipeline
    result = await pipeline.run(capture_ref="local:" + image_path)
    
    # Save output
    if result.get("video_asset"):
        import shutil
        asset = result["video_asset"]
        src = asset.get("url") or asset.get("output_ref", "")
        if src and os.path.exists(src):
            shutil.copy2(src, output_path)
            print(f"Video saved to {output_path}")
    
    return result


def main():
    parser = argparse.ArgumentParser(description="Wan 2.1 Standalone Inference")
    parser.add_argument("--image", required=True, help="Path to input image")
    parser.add_argument("--experience", default="aurora", 
                        choices=["aurora", "mirage", "pulse", "driftwood"],
                        help="Experience/theme ID")
    parser.add_argument("--output", default="output.mp4", help="Output video path")
    parser.add_argument("--steps", type=int, default=28, help="Number of inference steps")
    parser.add_argument("--guidance", type=float, default=7.5, help="Guidance scale")
    parser.add_argument("--seed", type=int, help="Random seed (optional)")
    parser.add_argument("--fps", type=int, default=12, help="Output FPS")
    parser.add_argument("--duration", type=float, default=4.0, help="Duration in seconds")
    parser.add_argument("--resolution", default="480x832", help="Output resolution (WxH)")
    parser.add_argument("--model-variant", default="wan2.1-i2v-14b-480p", help="Model variant")
    parser.add_argument("--precision", choices=["fp16", "bf16", "fp32"], default="bf16")
    parser.add_argument("--model-repo", default="Wan-AI/Wan2.1-I2V-14B-480P-Diffusers", help="HF model repo")
    parser.add_argument("--local-path", help="Local model path (optional)")
    parser.add_argument("--offload", action="store_true", help="Enable CPU offload")
    # Default ON: small GPUs need disk-streamed loading; A6000 users pass --no-cpu-offload.
    parser.add_argument(
        "--cpu-offload",
        action=argparse.BooleanOptionalAction,
        default=True,
        help="Enable sequential CPU offload (default: on)",
    )
    
    args = parser.parse_args()
    
    # Parse resolution
    try:
        width, height = map(int, args.resolution.split("x"))
    except ValueError:
        print("Error: Resolution must be in format WIDTHxHEIGHT (e.g., 720x1280)")
        sys.exit(1)
    
    # Build configs
    model_config = WanModelConfig(
        variant=WanModelVariant(args.model_variant),
        precision=WanPrecision(args.precision),
        model_repo=args.model_repo,
        local_model_path=args.local_path if args.local_path else None,
        enable_offload=args.offload,
        offload_to_cpu=args.cpu_offload,
        device="cuda" if torch.cuda.is_available() else "cpu",
    )
    
    gen_config = WanGenerationConfig(
        prompt="",  # Will be filled by experience
        negative_prompt="",
        num_inference_steps=args.steps,
        guidance_scale=args.guidance,
        seed=args.seed,
        fps=args.fps,
        duration_sec=args.duration,
        width=width,
        height=height,
    )
    
    # Run inference
    print(f"Starting inference...")
    print(f"  Image: {args.image}")
    print(f"  Experience: {args.experience}")
    print(f"  Output: {args.output}")
    print(f"  Resolution: {args.resolution}")
    print(f"  Steps: {args.steps}")
    print(f"  Guidance: {args.guidance}")
    print(f"  FPS: {args.fps}")
    print(f"  Duration: {args.duration}s")
    
    try:
        result = asyncio.run(run_inference(
            image_path=args.image,
            experience_id=args.experience,
            output_path=args.output,
            model_config=model_config,
            generation_config=gen_config,
        ))
        
        print("Inference completed successfully!")
        print(f"Result: {result}")
        
    except Exception as e:
        print(f"Error: {e}")
        import traceback
        traceback.print_exc()
        sys.exit(1)


if __name__ == "__main__":
    import uuid
    import torch
    from PIL import Image
    import shutil
    from aura_backend.inference.wan_config import (
        WanModelConfig,
        WanGenerationConfig,
        WanModelVariant,
        WanPrecision,
    )
    from aura_backend.inference.wan_loader import get_wan_loader
    from aura_backend.inference.wan_pipeline import WanInferencePipeline, WanPipelineFactory
    from aura_backend.inference.wan_loader import get_wan_loader
    from aura_backend.inference.wan_config import build_wan_prompt, WanGenerationConfig
    
    main()