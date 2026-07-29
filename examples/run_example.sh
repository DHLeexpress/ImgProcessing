#!/usr/bin/env bash
set -euo pipefail

ROOT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")/.." && pwd)"
cd "$ROOT_DIR"

python multi_video_motion_composite.py \
  --clip examples/input/KakaoTalk_Video_2026-07-29-16-14-16.mp4 18 39 \
  --steps 16 \
  --forget 0.86 \
  --max-opacity 0.78 \
  --min-opacity 0.08 \
  --output examples/output/reproduced_composite.png \
  --save-background examples/output/reproduced_background.png \
  --save-mask-preview examples/output/reproduced_mask_preview.png
