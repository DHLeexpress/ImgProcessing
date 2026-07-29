# Fixed-Background Multi-Video Motion Composite

Create a paper-style **overlapped motion image** from one or more fixed-camera videos.
The script samples a finite number of poses from each time interval, estimates one shared background, and overlays only the moving foreground.

The intended use case is a drone or robot recorded several times from the same camera pose:

- all videos share the same static background;
- each video can use a different start and finish time;
- each interval is discretized into a requested number of poses;
- pose opacity follows an exponential forgetting schedule;
- bright drone LEDs are preserved independently, so the light remains visible along the trajectory;
- all runs are merged into one output image.

## Repository structure

```text
.
├── multi_video_motion_composite.py
├── requirements.txt
└── examples
    ├── input
    │   └── KakaoTalk_Video_2026-07-29-16-14-16.mp4
    ├── output
    │   ├── drone_composite_18s_39s.png
    │   ├── drone_estimated_background.png
    │   └── drone_mask_preview.png
    └── run_example.sh
```

## Installation

Python 3.9 or newer is recommended.

```bash
python -m venv .venv
source .venv/bin/activate       # macOS/Linux
# .venv\Scripts\activate        # Windows PowerShell

pip install -r requirements.txt
```

## Reproduce the included 18-39 s example

From the repository root:

```bash
python multi_video_motion_composite.py \
  --clip examples/input/KakaoTalk_Video_2026-07-29-16-14-16.mp4 18 39 \
  --steps 16 \
  --forget 0.86 \
  --max-opacity 0.78 \
  --min-opacity 0.08 \
  --output examples/output/reproduced_composite.png \
  --save-background examples/output/reproduced_background.png \
  --save-mask-preview examples/output/reproduced_mask_preview.png
```

Or run:

```bash
bash examples/run_example.sh
```

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

Every input video must have the same resolution and a fixed, aligned camera view. The videos may have different durations and requested time intervals.

## Exponential opacity

For a clip with `N` sampled poses, pose `i` uses

```text
alpha_i = max(min_opacity, max_opacity * forget^(N - 1 - i))
```

Therefore, the newest pose does **not** need to be 100% opaque. With

```text
--forget 0.84 --max-opacity 0.78 --min-opacity 0.05
```

recent poses are stronger, older poses fade exponentially, and no pose falls below opacity `0.05`.

### `--opacity-scope per-video`

The opacity schedule restarts for each video. This is usually the correct choice when several independent trials are merged and should have equal visual importance.

### `--opacity-scope global`

One opacity schedule is applied across all sampled poses in the order the clips are listed. Later videos therefore appear more strongly.

## Keeping drone lights visible

The foreground pose and bright LEDs are composited separately:

1. The moving drone body uses the exponentially decayed pose opacity.
2. Pixels that are sufficiently bright and brighter than the shared background use a separate screen blend controlled by `--light-opacity`.

This lets the light remain visible at every sampled position without repeatedly darkening or ghosting the static background.

Useful parameters:

```text
--light-threshold 145   absolute brightness required for a light pixel
--light-delta 28        brightness increase relative to the background
--light-opacity 0.95    strength of preserved light pixels
```

For a dim LED, try:

```bash
--light-threshold 100 --light-delta 15
```

If static background lights are incorrectly detected, increase the thresholds:

```bash
--light-threshold 180 --light-delta 40
```

Disable the separate light treatment with:

```bash
--disable-light-preserve
```

## Main options

| Option | Meaning |
|---|---|
| `--clip VIDEO START END` | Video and interval in seconds; repeat for multiple videos. |
| `--steps N` | Number of discretized poses sampled from each interval. |
| `--forget RHO` | Exponential retention factor in `(0, 1]`; lower values fade older poses faster. |
| `--max-opacity A` | Opacity of the newest pose. |
| `--min-opacity A` | Lower bound on pose opacity. |
| `--opacity-scope` | `per-video` or `global`. |
| `--background IMAGE` | Optional clean background image instead of median estimation. |
| `--background-samples N` | Number of frames used for temporal-median background estimation. |
| `--diff-threshold` | Minimum frame/background difference treated as foreground. |
| `--mask-softness` | Width of the soft foreground transition. |
| `--mask-dilate` | Dilation width used to retain thin drone structures. |
| `--mask-blur` | Foreground-mask edge feathering. |
| `--light-threshold` | Absolute brightness threshold for moving LEDs. |
| `--light-delta` | Required brightness increase over the background. |
| `--light-opacity` | Preserved-light compositing strength. |
| `--output` | Composite PNG path. |
| `--save-background` | Optional estimated-background output path. |
| `--save-mask-preview` | Optional foreground/light mask contact sheet. |

Run the full CLI help with:

```bash
python multi_video_motion_composite.py --help
```

## Practical notes

- Use a tripod or otherwise keep the camera rigidly fixed.
- Do not crop, rotate, or change resolution between videos.
- If videos have small camera shifts, align them before running this script.
- A clean background image generally produces the best foreground mask; pass it with `--background`.
- Temporal-median estimation works best when the drone does not occupy the same pixel for most of the selected frames.
- Increase `--steps` for a denser trajectory, but too many samples can make the body look cluttered.
