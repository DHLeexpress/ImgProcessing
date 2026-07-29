#!/usr/bin/env python3
"""Create one long-exposure-style composite from one or more fixed-camera videos.

The script keeps a single shared background, samples a discrete number of poses
from each clip, and overlays only pixels that differ from the estimated
background. Pose opacity follows an exponential forgetting schedule. Bright
LED/light pixels can be preserved separately so that the light remains visible
at every sampled location.

Examples
--------
One video:
    python multi_video_motion_composite.py \
        --clip input.mp4 18 39 \
        --steps 14 --forget 0.84 --max-opacity 0.78 \
        --output composite.png

Multiple videos sharing the same background:
    python multi_video_motion_composite.py \
        --clip run1.mp4 4.0 16.0 \
        --clip run2.mp4 7.5 20.0 \
        --clip run3.mp4 2.0 13.0 \
        --steps 12 --forget 0.84 --opacity-scope per-video \
        --output merged_runs.png

Run without --clip to enter the video paths and times interactively.
"""

from __future__ import annotations

import argparse
import math
import sys
from dataclasses import dataclass
from pathlib import Path
from typing import Iterable, Sequence

import cv2
import numpy as np


@dataclass(frozen=True)
class ClipSpec:
    path: Path
    start: float
    end: float
    steps: int


@dataclass
class SampledClip:
    spec: ClipSpec
    times: list[float]
    frames: list[np.ndarray]


def parse_args() -> argparse.Namespace:
    parser = argparse.ArgumentParser(
        description=(
            "Overlay discretized poses from one or more fixed-background videos "
            "onto one shared background using exponential opacity decay."
        )
    )
    parser.add_argument(
        "--clip",
        action="append",
        nargs=3,
        metavar=("VIDEO", "START", "END"),
        help=(
            "Video path and interval in seconds. Repeat --clip for multiple videos. "
            "Example: --clip run.mp4 18 39"
        ),
    )
    parser.add_argument(
        "--steps",
        type=int,
        default=14,
        help="Number of sampled poses per video interval (default: 14).",
    )
    parser.add_argument(
        "--forget",
        type=float,
        default=0.84,
        help=(
            "Per-step exponential opacity retention in (0, 1]. "
            "For a pose k steps before the newest pose: alpha=max_alpha*forget^k. "
            "Lower values fade old poses faster (default: 0.84)."
        ),
    )
    parser.add_argument(
        "--max-opacity",
        type=float,
        default=0.78,
        help=(
            "Opacity of the newest sampled pose. It need not be 1.0 "
            "(default: 0.78)."
        ),
    )
    parser.add_argument(
        "--min-opacity",
        type=float,
        default=0.05,
        help="Lower bound applied to pose opacity (default: 0.05).",
    )
    parser.add_argument(
        "--opacity-scope",
        choices=("per-video", "global"),
        default="per-video",
        help=(
            "Reset the exponential schedule for every video, or apply one schedule "
            "across all videos in input order (default: per-video)."
        ),
    )
    parser.add_argument(
        "--background-samples",
        type=int,
        default=31,
        help=(
            "Maximum number of frames used to estimate the shared temporal-median "
            "background (default: 31)."
        ),
    )
    parser.add_argument(
        "--diff-threshold",
        type=float,
        default=8.0,
        help=(
            "Minimum per-pixel difference from the background before a pixel is "
            "treated as foreground (0-255 scale; default: 8)."
        ),
    )
    parser.add_argument(
        "--mask-softness",
        type=float,
        default=18.0,
        help=(
            "Difference range over which the foreground mask rises from 0 to 1 "
            "(default: 18)."
        ),
    )
    parser.add_argument(
        "--mask-dilate",
        type=int,
        default=3,
        help=(
            "Odd dilation-kernel width used to keep thin drone structures. "
            "Use 0 or 1 to disable (default: 3)."
        ),
    )
    parser.add_argument(
        "--mask-blur",
        type=float,
        default=1.2,
        help="Gaussian sigma used to feather the mask edge (default: 1.2).",
    )
    parser.add_argument(
        "--light-threshold",
        type=int,
        default=145,
        help=(
            "Brightness threshold for LED/light preservation on the V channel "
            "(0-255; default: 145)."
        ),
    )
    parser.add_argument(
        "--light-delta",
        type=int,
        default=28,
        help=(
            "Required brightness increase over the background for a pixel to count "
            "as a moving light (default: 28)."
        ),
    )
    parser.add_argument(
        "--light-opacity",
        type=float,
        default=0.95,
        help=(
            "Opacity used for detected LED/light pixels. This is independent of pose "
            "opacity so lights remain visible along the full path (default: 0.95)."
        ),
    )
    parser.add_argument(
        "--disable-light-preserve",
        action="store_true",
        help="Do not give bright LED/light pixels separate high-opacity treatment.",
    )
    parser.add_argument(
        "--background",
        type=Path,
        default=None,
        help=(
            "Optional clean background image. When omitted, a shared temporal median "
            "is estimated from all input clips."
        ),
    )
    parser.add_argument(
        "--output",
        type=Path,
        default=Path("motion_composite.png"),
        help="Output image path (default: motion_composite.png).",
    )
    parser.add_argument(
        "--save-background",
        type=Path,
        default=None,
        help="Optional path at which to save the estimated shared background.",
    )
    parser.add_argument(
        "--save-mask-preview",
        type=Path,
        default=None,
        help="Optional path for a contact sheet of foreground-mask previews.",
    )
    return parser.parse_args()


def interactive_clips(default_steps: int) -> list[ClipSpec]:
    print("No --clip arguments were provided; entering interactive mode.")
    while True:
        raw = input("Number of videos: ").strip()
        try:
            count = int(raw)
            if count > 0:
                break
        except ValueError:
            pass
        print("Please enter a positive integer.")

    clips: list[ClipSpec] = []
    for i in range(count):
        print(f"\nVideo {i + 1}/{count}")
        path = Path(input("  path: ").strip()).expanduser()
        start = float(input("  start time [s]: ").strip())
        end = float(input("  finish time [s]: ").strip())
        steps_raw = input(f"  number of poses [{default_steps}]: ").strip()
        steps = int(steps_raw) if steps_raw else default_steps
        clips.append(ClipSpec(path=path, start=start, end=end, steps=steps))
    return clips


def validate_unit_interval(name: str, value: float, allow_zero: bool = True) -> None:
    lower_ok = value >= 0.0 if allow_zero else value > 0.0
    if not lower_ok or value > 1.0:
        bracket = "[0, 1]" if allow_zero else "(0, 1]"
        raise ValueError(f"{name} must be in {bracket}; received {value}.")


def video_metadata(path: Path) -> tuple[float, int, int, float]:
    cap = cv2.VideoCapture(str(path))
    if not cap.isOpened():
        raise RuntimeError(f"Could not open video: {path}")
    fps = float(cap.get(cv2.CAP_PROP_FPS))
    frame_count = int(cap.get(cv2.CAP_PROP_FRAME_COUNT))
    width = int(cap.get(cv2.CAP_PROP_FRAME_WIDTH))
    height = int(cap.get(cv2.CAP_PROP_FRAME_HEIGHT))
    cap.release()
    if fps <= 0 or frame_count <= 0 or width <= 0 or height <= 0:
        raise RuntimeError(f"Invalid video metadata: {path}")
    duration = frame_count / fps
    return fps, width, height, duration


def read_frame_at(cap: cv2.VideoCapture, time_s: float) -> np.ndarray:
    cap.set(cv2.CAP_PROP_POS_MSEC, float(time_s) * 1000.0)
    ok, frame = cap.read()
    if not ok or frame is None:
        raise RuntimeError(f"Could not decode a frame at {time_s:.3f} s.")
    return frame


def sample_clip(spec: ClipSpec, expected_size: tuple[int, int] | None) -> SampledClip:
    fps, width, height, duration = video_metadata(spec.path)
    del fps
    if expected_size is not None and (width, height) != expected_size:
        raise ValueError(
            f"All videos must share one resolution. {spec.path} is {width}x{height}, "
            f"expected {expected_size[0]}x{expected_size[1]}."
        )
    if spec.steps < 1:
        raise ValueError(f"steps must be positive for {spec.path}.")
    if spec.start < 0 or spec.end <= spec.start:
        raise ValueError(
            f"Invalid interval for {spec.path}: start={spec.start}, end={spec.end}."
        )
    if spec.end > duration + 0.10:
        raise ValueError(
            f"Requested end time {spec.end:.3f}s exceeds duration "
            f"{duration:.3f}s for {spec.path}."
        )

    if spec.steps == 1:
        times = [0.5 * (spec.start + spec.end)]
    else:
        times = np.linspace(spec.start, min(spec.end, duration - 1e-3), spec.steps).tolist()

    cap = cv2.VideoCapture(str(spec.path))
    if not cap.isOpened():
        raise RuntimeError(f"Could not open video: {spec.path}")
    try:
        frames = [read_frame_at(cap, t) for t in times]
    finally:
        cap.release()
    return SampledClip(spec=spec, times=times, frames=frames)


def stratified_background_frames(
    clips: Sequence[ClipSpec], max_samples: int, expected_size: tuple[int, int]
) -> list[np.ndarray]:
    """Collect a bounded number of frames distributed across all intervals."""
    if max_samples < 1:
        raise ValueError("background-samples must be positive.")

    durations = np.array([c.end - c.start for c in clips], dtype=np.float64)
    if np.any(durations <= 0):
        raise ValueError("Every clip must have positive duration.")
    weights = durations / durations.sum()
    raw_counts = np.maximum(2, np.floor(weights * max_samples).astype(int))

    while raw_counts.sum() > max_samples and np.any(raw_counts > 2):
        idx = int(np.argmax(raw_counts))
        raw_counts[idx] -= 1
    while raw_counts.sum() < max_samples:
        residual = weights * max_samples - raw_counts
        raw_counts[int(np.argmax(residual))] += 1

    frames: list[np.ndarray] = []
    for spec, count in zip(clips, raw_counts.tolist()):
        _, width, height, duration = video_metadata(spec.path)
        if (width, height) != expected_size:
            raise ValueError(
                f"All videos must share one resolution. {spec.path} is {width}x{height}, "
                f"expected {expected_size[0]}x{expected_size[1]}."
            )
        cap = cv2.VideoCapture(str(spec.path))
        if not cap.isOpened():
            raise RuntimeError(f"Could not open video: {spec.path}")
        try:
            end = min(spec.end, duration - 1e-3)
            fractions = (np.arange(count, dtype=np.float64) + 0.5) / count
            times = spec.start + fractions * (end - spec.start)
            for t in times:
                frames.append(read_frame_at(cap, float(t)))
        finally:
            cap.release()
    return frames


def temporal_median_background(frames: Sequence[np.ndarray]) -> np.ndarray:
    if not frames:
        raise ValueError("Cannot estimate a background from zero frames.")
    shape = frames[0].shape
    if any(frame.shape != shape for frame in frames):
        raise ValueError("All background-estimation frames must have the same shape.")

    height, width, channels = shape
    output = np.empty(shape, dtype=np.uint8)
    strip_rows = max(32, min(192, int(2.5e8 / (len(frames) * width * channels))))
    for y0 in range(0, height, strip_rows):
        y1 = min(height, y0 + strip_rows)
        stack = np.stack([frame[y0:y1] for frame in frames], axis=0)
        output[y0:y1] = np.median(stack, axis=0).astype(np.uint8)
    return output


def load_or_estimate_background(
    path: Path | None,
    clips: Sequence[ClipSpec],
    max_samples: int,
    expected_size: tuple[int, int],
) -> np.ndarray:
    if path is not None:
        background = cv2.imread(str(path), cv2.IMREAD_COLOR)
        if background is None:
            raise RuntimeError(f"Could not read background image: {path}")
        height, width = background.shape[:2]
        if (width, height) != expected_size:
            raise ValueError(
                f"Background is {width}x{height}, expected "
                f"{expected_size[0]}x{expected_size[1]}."
            )
        return background

    candidates = stratified_background_frames(clips, max_samples, expected_size)
    return temporal_median_background(candidates)


def foreground_mask(
    frame: np.ndarray,
    background: np.ndarray,
    threshold: float,
    softness: float,
    dilate_width: int,
    blur_sigma: float,
) -> np.ndarray:
    frame_f = frame.astype(np.float32)
    bg_f = background.astype(np.float32)
    diff = np.linalg.norm(frame_f - bg_f, axis=2) / math.sqrt(3.0)
    if softness <= 0:
        mask = (diff >= threshold).astype(np.float32)
    else:
        mask = np.clip((diff - threshold) / softness, 0.0, 1.0).astype(np.float32)

    if dilate_width > 1:
        width = dilate_width if dilate_width % 2 == 1 else dilate_width + 1
        kernel = cv2.getStructuringElement(cv2.MORPH_ELLIPSE, (width, width))
        mask = cv2.dilate(mask, kernel, iterations=1)
    if blur_sigma > 0:
        mask = cv2.GaussianBlur(mask, (0, 0), blur_sigma)
    return np.clip(mask, 0.0, 1.0)


def light_mask(
    frame: np.ndarray,
    background: np.ndarray,
    brightness_threshold: int,
    delta_threshold: int,
) -> np.ndarray:
    hsv_frame = cv2.cvtColor(frame, cv2.COLOR_BGR2HSV)
    hsv_bg = cv2.cvtColor(background, cv2.COLOR_BGR2HSV)
    value = hsv_frame[:, :, 2].astype(np.int16)
    bg_value = hsv_bg[:, :, 2].astype(np.int16)

    mask = (value >= brightness_threshold) & ((value - bg_value) >= delta_threshold)
    mask_u8 = mask.astype(np.uint8) * 255
    kernel = cv2.getStructuringElement(cv2.MORPH_ELLIPSE, (3, 3))
    mask_u8 = cv2.dilate(mask_u8, kernel, iterations=1)
    mask_f = cv2.GaussianBlur(mask_u8.astype(np.float32) / 255.0, (0, 0), 0.8)
    return np.clip(mask_f, 0.0, 1.0)


def alpha_blend(base: np.ndarray, layer: np.ndarray, alpha: np.ndarray) -> np.ndarray:
    """Blend float32 BGR arrays using an HxW or HxWx1 alpha map."""
    if alpha.ndim == 2:
        alpha = alpha[:, :, None]
    return base * (1.0 - alpha) + layer * alpha


def screen_blend(base: np.ndarray, layer: np.ndarray) -> np.ndarray:
    """Screen blend for bright light trails, inputs in [0, 255]."""
    return 255.0 - (255.0 - base) * (255.0 - layer) / 255.0


def opacity_schedule(
    count: int, forget: float, max_opacity: float, min_opacity: float
) -> list[float]:
    if count <= 0:
        return []
    return [
        max(min_opacity, max_opacity * (forget ** (count - 1 - i)))
        for i in range(count)
    ]


def compose(
    sampled_clips: Sequence[SampledClip],
    background: np.ndarray,
    forget: float,
    max_opacity: float,
    min_opacity: float,
    opacity_scope: str,
    diff_threshold: float,
    mask_softness: float,
    mask_dilate: int,
    mask_blur: float,
    preserve_lights: bool,
    light_threshold: int,
    light_delta: int,
    light_opacity: float,
) -> tuple[np.ndarray, list[np.ndarray]]:
    composite = background.astype(np.float32)
    mask_previews: list[np.ndarray] = []

    if opacity_scope == "global":
        total = sum(len(c.frames) for c in sampled_clips)
        global_alphas = iter(opacity_schedule(total, forget, max_opacity, min_opacity))
    else:
        global_alphas = None

    for clip in sampled_clips:
        if opacity_scope == "per-video":
            alphas: Iterable[float] = opacity_schedule(
                len(clip.frames), forget, max_opacity, min_opacity
            )
        else:
            assert global_alphas is not None
            alphas = global_alphas

        for frame, pose_alpha in zip(clip.frames, alphas):
            fg = foreground_mask(
                frame,
                background,
                threshold=diff_threshold,
                softness=mask_softness,
                dilate_width=mask_dilate,
                blur_sigma=mask_blur,
            )
            alpha = np.clip(fg * pose_alpha, 0.0, 1.0)
            composite = alpha_blend(composite, frame.astype(np.float32), alpha)

            if preserve_lights:
                lm = light_mask(
                    frame,
                    background,
                    brightness_threshold=light_threshold,
                    delta_threshold=light_delta,
                )
                light_alpha_map = np.clip(lm * light_opacity, 0.0, 1.0)
                screened = screen_blend(composite, frame.astype(np.float32))
                composite = alpha_blend(composite, screened, light_alpha_map)
            else:
                lm = np.zeros_like(fg)

            preview = np.zeros((*fg.shape, 3), dtype=np.uint8)
            preview[:, :, 2] = np.clip(fg * 255.0, 0, 255).astype(np.uint8)
            preview[:, :, 1] = np.clip(lm * 255.0, 0, 255).astype(np.uint8)
            mask_previews.append(preview)

    return np.clip(composite, 0, 255).astype(np.uint8), mask_previews


def save_contact_sheet(images: Sequence[np.ndarray], path: Path) -> None:
    if not images:
        return
    thumb_width = 480
    h, w = images[0].shape[:2]
    thumb_height = max(1, round(h * thumb_width / w))
    thumbs = [cv2.resize(img, (thumb_width, thumb_height)) for img in images]
    columns = min(4, len(thumbs))
    rows = math.ceil(len(thumbs) / columns)
    sheet = np.zeros((rows * thumb_height, columns * thumb_width, 3), dtype=np.uint8)
    for i, thumb in enumerate(thumbs):
        r, c = divmod(i, columns)
        sheet[
            r * thumb_height : (r + 1) * thumb_height,
            c * thumb_width : (c + 1) * thumb_width,
        ] = thumb
    path.parent.mkdir(parents=True, exist_ok=True)
    if not cv2.imwrite(str(path), sheet):
        raise RuntimeError(f"Could not write mask preview: {path}")


def main() -> int:
    args = parse_args()

    try:
        validate_unit_interval("forget", args.forget, allow_zero=False)
        validate_unit_interval("max-opacity", args.max_opacity)
        validate_unit_interval("min-opacity", args.min_opacity)
        validate_unit_interval("light-opacity", args.light_opacity)
        if args.min_opacity > args.max_opacity:
            raise ValueError("min-opacity cannot exceed max-opacity.")
        if args.steps < 1:
            raise ValueError("steps must be positive.")
        if args.diff_threshold < 0 or args.mask_softness < 0:
            raise ValueError("diff-threshold and mask-softness cannot be negative.")

        if args.clip:
            clips = [
                ClipSpec(
                    path=Path(raw_path).expanduser(),
                    start=float(raw_start),
                    end=float(raw_end),
                    steps=args.steps,
                )
                for raw_path, raw_start, raw_end in args.clip
            ]
        else:
            clips = interactive_clips(args.steps)

        for clip in clips:
            if not clip.path.is_file():
                raise FileNotFoundError(f"Video does not exist: {clip.path}")

        _, width, height, _ = video_metadata(clips[0].path)
        expected_size = (width, height)
        sampled_clips = [sample_clip(clip, expected_size) for clip in clips]

        print("Estimating one shared background...")
        background = load_or_estimate_background(
            args.background,
            clips,
            args.background_samples,
            expected_size,
        )

        print(
            f"Compositing {sum(len(c.frames) for c in sampled_clips)} poses from "
            f"{len(sampled_clips)} video(s)..."
        )
        composite, mask_previews = compose(
            sampled_clips=sampled_clips,
            background=background,
            forget=args.forget,
            max_opacity=args.max_opacity,
            min_opacity=args.min_opacity,
            opacity_scope=args.opacity_scope,
            diff_threshold=args.diff_threshold,
            mask_softness=args.mask_softness,
            mask_dilate=args.mask_dilate,
            mask_blur=args.mask_blur,
            preserve_lights=not args.disable_light_preserve,
            light_threshold=args.light_threshold,
            light_delta=args.light_delta,
            light_opacity=args.light_opacity,
        )

        args.output.parent.mkdir(parents=True, exist_ok=True)
        if not cv2.imwrite(str(args.output), composite):
            raise RuntimeError(f"Could not write output image: {args.output}")

        if args.save_background is not None:
            args.save_background.parent.mkdir(parents=True, exist_ok=True)
            if not cv2.imwrite(str(args.save_background), background):
                raise RuntimeError(
                    f"Could not write background image: {args.save_background}"
                )

        if args.save_mask_preview is not None:
            save_contact_sheet(mask_previews, args.save_mask_preview)

        print(f"Saved composite: {args.output.resolve()}")
        if args.save_background is not None:
            print(f"Saved background: {args.save_background.resolve()}")
        if args.save_mask_preview is not None:
            print(f"Saved mask preview: {args.save_mask_preview.resolve()}")
        return 0

    except (ValueError, RuntimeError, FileNotFoundError) as exc:
        print(f"Error: {exc}", file=sys.stderr)
        return 2


if __name__ == "__main__":
    raise SystemExit(main())
