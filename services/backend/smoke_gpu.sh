#!/usr/bin/env bash
# AURA GPU smoke test with fail-fast gates.
#
# Order (each gate stops the run in seconds if unmet — the 14B model only
# loads after ALL gates pass):
#   0. venv active + aura_backend importable
#   1. CUDA visible to torch
#   2. source video present
#   3. cv2 available (frame extraction needs no ffmpeg/apt)
#   4. frame extracted AND decodable (non-empty JPEG)
#   5. >=100GB free on /workspace (weights + outputs)
#   6. run inference in background, follow /tmp/smoke.log
#
# Usage: bash smoke_gpu.sh [--steps 16] [--experience aurora]
set -euo pipefail

STEPS=16
EXPERIENCE=aurora
while [[ $# -gt 0 ]]; do
  case "$1" in
    --steps) STEPS="$2"; shift 2;;
    --experience) EXPERIENCE="$2"; shift 2;;
    *) echo "unknown arg: $1" >&2; exit 2;;
  esac
done

REPO_ROOT="$(cd "$(dirname "${BASH_SOURCE[0]}")/../.." && pwd)"
BACKEND="$REPO_ROOT/services/backend"
SRC_VIDEO="$REPO_ROOT/apps/stage/public/videos/curated-a.mp4"
INPUT_IMG=/tmp/smoke_input.jpg
OUTPUT_MP4=/tmp/smoke.mp4

fail() { echo "GATE FAILED: $1" >&2; exit 1; }
ok() { echo "GATE OK: $1"; }

[[ -n "${VIRTUAL_ENV:-}" ]] || fail "venv not active. Run: source /workspace/FortressForge/.venv/bin/activate"
python -c "import aura_backend" 2>/dev/null || fail "aura_backend not importable. Reinstall: pip install -e ./services/backend"
ok "venv + package"

python -c "import torch; assert torch.cuda.is_available(), 'no cuda'" 2>/dev/null \
  || fail "CUDA not visible to torch"
ok "cuda: $(python -c 'import torch; print(torch.cuda.get_device_name(0))')"

[[ -f "$SRC_VIDEO" ]] || fail "source video missing: $SRC_VIDEO (git pull?)"
ok "source video"

python -c "import cv2" 2>/dev/null || fail "opencv (cv2) missing: pip install opencv-python"
ok "cv2 frame extraction (no ffmpeg needed)"

python3 - "$SRC_VIDEO" "$INPUT_IMG" <<'EOF'
import sys
import cv2
cap = cv2.VideoCapture(sys.argv[1])
ok, frame = cap.read()
cap.release()
assert ok and frame is not None, "could not decode first frame"
# Center-crop to 9:16 portrait (the pipeline resizes unconditionally, but a
# landscape frame stretched to portrait would distort the subject).
h, w = frame.shape[:2]
target = 9 / 16
if w / h > target:  # too wide -> crop width
    nw = int(h * target)
    x = (w - nw) // 2
    frame = frame[:, x:x + nw]
else:  # too tall -> crop height
    nh = int(w / target)
    y = (h - nh) // 2
    frame = frame[y:y + nh, :]
assert cv2.imwrite(sys.argv[2], frame), "could not write jpeg"
EOF
[[ -s "$INPUT_IMG" ]] || fail "extracted frame is empty"
python -c "from PIL import Image; Image.open('$INPUT_IMG').verify()" \
  || fail "extracted image not decodable"
ok "input image $(du -h "$INPUT_IMG" | cut -f1)"

FREE_KB=$(df -k /workspace | tail -1 | awk '{print $4}')
[[ "$FREE_KB" -gt 104857600 ]] || fail "only $((FREE_KB / 1024 / 1024))GB free on /workspace, need 100GB+"
ok "disk free $((FREE_KB / 1024 / 1024))GB"

export HF_HOME=/workspace/.hf-cache HF_HUB_CACHE=/workspace/.hf-cache
cd "$BACKEND"
nohup python -m aura_backend.inference.wan_standalone \
  --image "$INPUT_IMG" --experience "$EXPERIENCE" \
  --output "$OUTPUT_MP4" --steps "$STEPS" > /tmp/smoke.log 2>&1 &
echo "render started pid $! — follow with: tail -f /tmp/smoke.log"
echo "verify at the end with: ls -la /tmp/smoke.mp4"
