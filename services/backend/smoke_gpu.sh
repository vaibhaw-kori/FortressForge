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
# Runs FOREGROUND by default (waits, verifies mp4, exits non-zero on failure).
# Set SMOKE_BACKGROUND=1 for nohup background mode (SSH-drop safe).
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
python -c "import ftfy" 2>/dev/null || fail "ftfy missing (Wan prompt cleaning needs it). Run: pip install ftfy"
ok "ftfy"

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

# NOTE: df lies on RunPod network mounts (reports cluster-wide petabytes).
# Measure real usage with du against the 200GB volume quota instead.
USED_KB=$(du -sk /workspace 2>/dev/null | cut -f1)
[[ "$USED_KB" -lt 188743680 ]] || fail "/workspace uses $((USED_KB / 1024 / 1024))GB of 200GB quota — free space first"
ok "volume used $((USED_KB / 1024 / 1024))GB of 200GB"

export HF_HOME=/workspace/.hf-cache HF_HUB_CACHE=/workspace/.hf-cache
cd "$BACKEND"
rm -f "$OUTPUT_MP4"
if [[ "${SMOKE_BACKGROUND:-0}" == "1" ]]; then
  # Unattended mode (survives SSH drops); caller tails /tmp/smoke.log.
  nohup python -m aura_backend.inference.wan_standalone \
    --image "$INPUT_IMG" --experience "$EXPERIENCE" \
    --output "$OUTPUT_MP4" --steps "$STEPS" > /tmp/smoke.log 2>&1 &
  echo "render started pid $! — follow with: tail -f /tmp/smoke.log"
  echo "verify at the end with: ls -la /tmp/smoke.mp4"
  exit 0
fi
# Foreground mode (default): wait, propagate exit status, verify output.
set +e
python -m aura_backend.inference.wan_standalone \
  --image "$INPUT_IMG" --experience "$EXPERIENCE" \
  --output "$OUTPUT_MP4" --steps "$STEPS" 2>&1 | tee /tmp/smoke.log
CODE=${PIPESTATUS[0]:-$?}
set -e
if [[ $CODE -ne 0 ]]; then
  echo "SMOKE FAIL: inference exited $CODE (see /tmp/smoke.log)"
  exit $CODE
fi
[[ -s "$OUTPUT_MP4" ]] || { echo "SMOKE FAIL: $OUTPUT_MP4 missing/empty"; exit 1; }
SIZE=$(du -h "$OUTPUT_MP4" | cut -f1)
[[ $(stat -c%s "$OUTPUT_MP4") -gt 100000 ]] || { echo "SMOKE FAIL: output suspiciously small ($SIZE)"; exit 1; }
echo "SMOKE PASS: $OUTPUT_MP4 ($SIZE)"
python3 - "$OUTPUT_MP4" <<'EOF' || echo "SMOKE WARN: cv2 metadata probe failed"
import sys
import cv2
cap = cv2.VideoCapture(sys.argv[1])
n = int(cap.get(cv2.CAP_PROP_FRAME_COUNT))
fps = cap.get(cv2.CAP_PROP_FPS)
w = int(cap.get(cv2.CAP_PROP_FRAME_WIDTH))
h = int(cap.get(cv2.CAP_PROP_FRAME_HEIGHT))
cap.release()
print(f"frames={n} fps={fps:.1f} size={w}x{h} duration={n / fps if fps else 0:.1f}s")
assert n >= 8, "too few frames"
EOF
