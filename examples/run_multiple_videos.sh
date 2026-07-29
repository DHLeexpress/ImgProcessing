#!/usr/bin/env bash
set -e

mkdir -p outputs
python multi_video_motion_composite.py \
  --clip data/run1.mp4 18 39 \
  --clip data/run2.mp4 5 24 \
  --clip data/run3.mp4 10 31 \
  --steps 12 \
  --forget 0.84 \
  --max-opacity 0.78 \
  --min-opacity 0.05 \
  --opacity-scope per-video \
  --output outputs/merged_drone_runs.png \
  --save-background outputs/shared_background.png \
  --save-mask-preview outputs/mask_preview.png
