#!/usr/bin/env bash
set -e

VIDEO_PATH="$1"
mkdir -p outputs
python multi_video_motion_composite.py \
  --clip "$VIDEO_PATH" 18 39 \
  --steps 16 \
  --forget 0.86 \
  --max-opacity 0.78 \
  --min-opacity 0.08 \
  --output outputs/drone_composite_18s_39s.png \
  --save-background outputs/drone_estimated_background.png \
  --save-mask-preview outputs/drone_mask_preview.png
