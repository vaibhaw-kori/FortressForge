# AURA Inference

Provider abstraction for AI video generation. Mirrors the contracts
exposed by the backend so we can iterate on models and providers
without touching job orchestration.

## Layout
```
src/aura_inference/
  __init__.py
  contracts.py    # Shared dataclasses (ProviderInput, ProviderHandle, ProviderResult)
  base.py         # VideoGenProvider ABC
  runpod.py       # RunPod serverless client
  self_hosted.py  # Self-hosted FastAPI worker (skeleton)
  fake.py         # CPU-only FFmpeg-based stub (offline dev)
```

The actual model loading (Stable Video Diffusion, AnimateDiff+IP-Adapter,
Wan2.1-Animate, etc.) lives behind `self_hosted.py` and is intentionally
**not** implemented in this scaffold — see TODO in that file.