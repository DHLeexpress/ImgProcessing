# Fixed-Background Multi-Video Motion Composite

Create a paper-style **overlapped motion image** from one or more fixed-camera videos.
The script samples a finite number of poses from each requested time interval, estimates one shared background, and overlays only the moving foreground.

This is intended for drone or robot experiments in which:

- every video uses the same fixed camera and static background;
- each video may use a different start and finish time;
- every interval is discretized into a requested number of poses;
- robot/drone opacity follows an exponential forgetting schedule;
- bright LEDs are preserved separately so the light remains visible along the trajectory;
- all videos are merged into one output image.

## Repository structure

```text
.
├── multi_video_motion_composite.py
├── requirements.txt
└── examples
    ├── run_example.sh
    └── run_multiple_videos.sh
```

Input videos are intentionally not committed. Put your own videos anywhere on your machine and pass their paths with `--clip`.

## Installation

Python 3.9 or newer is recommended.

```bash
python -m venv .venv
source .venv/bin/activate       # macOS/Linux
# .venv\Scripts\activate        # Windows PowerShell

pip install -r requirements.txt
```

## Quick start: one video, 18-39 seconds

```bash
python multi_video_motion_composite.py \
  --clip /path/to/KakaoTalk_Video_2026-07-29-16-14-16.mp4 18 39 \
  --steps 16 \
  --forget 0.86 \
  --max-opacity 0.78 \
  --min-opacity 0.08 \
  --output outputs/drone_composite_18s_39s.png \
  --save-background outputs/drone_estimated_background.png \
  --save-mask-preview outputs/drone_mask_preview.png
```

Equivalent helper script:

```bash
bash examples/run_example.sh /path/to/video.mp4
```

The helper script creates the `outputs/` directory and processes seconds 18 through 39.

## Merge several videos with the same background

Repeat `--clip VIDEO START END` once per video:

```bash
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
```

A ready-to-edit command template is also provided:

```bash
bash examples/run_multiple_videos.sh
```

Every video must have the same resolution and an aligned camera view. Durations and selected time intervals may differ.

## Exponential opacity

For a clip with `N` sampled poses, pose `i` uses

```text
alpha_i = max(min_opacity, max_opacity * forget^(N - 1 - i))
```

Therefore, the newest pose does **not** need to be 100% opaque. For example,

```text
--forget 0.84 --max-opacity 0.78 --min-opacity 0.05
```

makes recent poses stronger, fades older poses exponentially, and prevents any sampled pose from falling below opacity `0.05`.

### `--opacity-scope per-video`

The exponential schedule restarts for every video. This is usually the correct choice when independent experimental runs should have equal visual importance.

### `--opacity-scope global`

One schedule is applied across all sampled poses in the order the videos are listed. Later videos consequently appear more strongly.

## Keeping drone lights visible

The moving body and bright LEDs are composited separately:

1. The drone body uses the exponentially decayed pose opacity.
2. Pixels that are sufficiently bright and brighter than the shared background use an independent screen blend controlled by `--light-opacity`.

This preserves the light at every sampled position while avoiding repeated blending of the static background.

Useful parameters:

```text
--light-threshold 145   absolute brightness required for a light pixel
--light-delta 28        brightness increase relative to the background
--light-opacity 0.95    preserved-light compositing strength
```

For a dim LED, try:

```bash
--light-threshold 100 --light-delta 15
```

If static background lights are incorrectly detected, increase the thresholds:

```bash
--light-threshold 180 --light-delta 40
```

Disable separate LED preservation with:

```bash
--disable-light-preserve
```

## Main options

| Option | Meaning |
|---|---|
| `--clip VIDEO START END` | Video path and interval in seconds; repeat for multiple videos. |
| `--steps N` | Number of discretized poses sampled from each interval. |
| `--forget RHO` | Exponential retention factor in `(0, 1]`; lower values fade older poses faster. |
| `--max-opacity A` | Opacity of the newest sampled pose. |
| `--min-opacity A` | Lower bound on pose opacity. |
| `--opacity-scope` | `per-video` or `global`. |
| `--background IMAGE` | Optional clean background image instead of median estimation. |
| `--background-samples N` | Maximum number of frames used for temporal-median background estimation. |
| `--diff-threshold` | Minimum frame/background difference treated as foreground. |
| `--mask-softness` | Width of the soft foreground-mask transition. |
| `--mask-dilate` | Dilation width used to retain thin drone structures. |
| `--mask-blur` | Foreground-mask edge feathering. |
| `--light-threshold` | Absolute brightness threshold for moving LEDs. |
| `--light-delta` | Required brightness increase over the background. |
| `--light-opacity` | Preserved-light compositing strength. |
| `--output` | Composite PNG path. |
| `--save-background` | Optional estimated-background output path. |
| `--save-mask-preview` | Optional foreground/light mask contact sheet. |

Run the complete CLI help with:

```bash
python multi_video_motion_composite.py --help
```

## Practical notes

- Use a tripod or otherwise keep the camera rigidly fixed.
- Do not crop, rotate, or change resolution between videos.
- If the camera shifts slightly between runs, align the videos before processing.
- A clean background image usually produces the best foreground mask; pass it with `--background`.
- Temporal-median estimation works best when the drone does not occupy the same pixel in most selected frames.
- Increase `--steps` for a denser trajectory, but excessive sampling can make the body cluttered.
