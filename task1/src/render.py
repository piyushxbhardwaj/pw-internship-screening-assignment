"""Frame rendering + ffmpeg muxing.

Draws the background image each frame with every annotation event whose start
time has been reached (annotations persist once they appear), then pipes raw
BGR frames into ffmpeg together with the narration audio to produce an MP4.
"""

from __future__ import annotations

import math
import subprocess
from pathlib import Path
from typing import Any

import numpy as np
from PIL import Image, ImageDraw, ImageFont


FONT_DIR = Path("/usr/share/fonts/truetype/dejavu")
LABEL_FONT = str(FONT_DIR / "DejaVuSans-Bold.ttf")


COLORS = {
    "highlight": (255, 213, 79, 100),
    "box": (220, 53, 69, 255),
    "box_emph": (9, 105, 218, 255),
    "underline": (9, 105, 218, 255),
    "label_bg": (11, 42, 107, 255),
    "label_text": (255, 255, 255, 255),
    "arrow": (11, 42, 107, 255),
}


_LAYER_ORDER = {
    "highlight": 0,
    "underline": 1,
    "box": 2,
    "label": 3,
}


def _active_events(
    timeline: dict[str, Any],
    t: float,
) -> list[dict[str, Any]]:
    out = []

    for event in timeline["events"]:
        if event["start"] <= t:
            out.append(event)

    # Layer order so strokes sit on top of translucent fills.
    out.sort(
        key=lambda event: _LAYER_ORDER.get(
            event["action"],
            10,
        )
    )

    return out


def _draw_highlight(
    base: Image.Image,
    event: dict[str, Any],
) -> None:
    x1, y1, x2, y2 = event["region"]

    overlay = Image.new(
        "RGBA",
        base.size,
        (0, 0, 0, 0),
    )

    d = ImageDraw.Draw(overlay)

    d.rectangle(
        [x1 - 6, y1 - 3, x2 + 6, y2 + 6],
        fill=COLORS["highlight"],
    )

    composited = Image.alpha_composite(
        base.convert("RGBA"),
        overlay,
    )

    base.paste(
        composited.convert("RGB"),
        (0, 0),
    )


def _draw_box(
    base: Image.Image,
    event: dict[str, Any],
) -> None:
    if not event.get("region"):
        return

    x1, y1, x2, y2 = event["region"]

    color = (
        COLORS["box_emph"]
        if event.get("emphasized")
        else COLORS["box"]
    )

    width = (
        6
        if event.get("emphasized")
        else 4
    )

    d = ImageDraw.Draw(base)

    d.rectangle(
        [
            x1 - 8,
            y1 - 6,
            x2 + 8,
            y2 + 8,
        ],
        outline=color,
        width=width,
    )


def _draw_underline(
    base: Image.Image,
    event: dict[str, Any],
) -> None:
    x1, y1, x2, y2 = event["region"]

    d = ImageDraw.Draw(base)

    d.line(
        [
            (x1, y2 + 3),
            (x2, y2 + 3),
        ],
        fill=COLORS["underline"],
        width=4,
    )


def _draw_label(
    base: Image.Image,
    event: dict[str, Any],
    font_size: int = 16,
) -> None:
    """Draw a label that always stays inside the frame."""

    d = ImageDraw.Draw(base)

    text = event["text"]

    # Keep labels inside the frame.
    max_width = max(
        40,
        base.size[0] - 20,
    )

    font = ImageFont.truetype(
        LABEL_FONT,
        font_size,
    )

    # Shrink long formulas until they fit.
    while (
        d.textlength(text, font=font) > max_width
        and font_size > 9
    ):
        font_size -= 1

        font = ImageFont.truetype(
            LABEL_FONT,
            font_size,
        )

    text_width = d.textlength(
        text,
        font=font,
    )

    box_w = min(
        text_width + 20,
        max_width,
    )

    box_h = font_size + 16

    x1, y1, _, _ = event["region"]

    bx = min(
        x1 + 5,
        base.size[0] - box_w - 5,
    )

    by = min(
        y1 + 5,
        base.size[1] - box_h - 5,
    )

    # Prevent negative coordinates on very small images.
    bx = max(5, bx)
    by = max(5, by)

    d.rounded_rectangle(
        [
            bx,
            by,
            bx + box_w,
            by + box_h,
        ],
        radius=6,
        fill=COLORS["label_bg"],
    )

    d.text(
        (
            bx + 10,
            by + 8,
        ),
        text,
        font=font,
        fill=COLORS["label_text"],
    )

    # Draw arrow toward diagram centre.
    if event.get("arrow_to"):
        cx, cy = event["arrow_to"]

        ax = bx + box_w // 2
        ay = by + box_h

        d.line(
            [
                (ax, ay),
                (cx, cy),
            ],
            fill=COLORS["arrow"],
            width=2,
        )

        # Small arrowhead.
        angle = math.atan2(
            cy - ay,
            cx - ax,
        )

        for delta in (-0.5, 0.5):
            tip = (
                cx - 10 * math.cos(angle + delta),
                cy - 10 * math.sin(angle + delta),
            )

            d.line(
                [
                    (cx, cy),
                    tip,
                ],
                fill=COLORS["arrow"],
                width=2,
            )


def render(
    background_path: Path,
    audio_path: Path,
    timeline: dict[str, Any],
    output_path: Path,
) -> None:
    """Render annotated frames and mux with audio into an MP4."""

    fps = timeline.get(
        "fps",
        30,
    )

    duration = timeline["video_duration"]

    n_frames = int(
        round(duration * fps)
    )

    # ------------------------------------------------------------------
    # Load background.
    # ------------------------------------------------------------------

    base = Image.open(
        background_path
    ).convert("RGB")

    w, h = base.size

    # ------------------------------------------------------------------
    # H.264/yuv420p requires even dimensions.
    #
    # For example:
    #   485 x 182 -> 486 x 182
    #
    # Padding is used instead of resizing so the original content is
    # not distorted.
    # ------------------------------------------------------------------

    if w % 2 or h % 2:
        padded = Image.new(
            "RGB",
            (
                w + (w % 2),
                h + (h % 2),
            ),
            "white",
        )

        padded.paste(
            base,
            (0, 0),
        )

        base = padded

        w, h = base.size

    # ------------------------------------------------------------------
    # FFmpeg command.
    # ------------------------------------------------------------------

    cmd = [
        "ffmpeg",
        "-y",
        "-loglevel",
        "error",

        "-f",
        "rawvideo",

        "-pix_fmt",
        "bgr24",

        "-s",
        f"{w}x{h}",

        "-r",
        str(fps),

        "-i",
        "-",

        "-i",
        str(audio_path),

        "-c:v",
        "libx264",

        "-preset",
        "veryfast",

        "-crf",
        "23",

        "-pix_fmt",
        "yuv420p",

        "-c:a",
        "aac",

        "-shortest",

        "-movflags",
        "+faststart",

        str(output_path),
    ]

    proc = subprocess.Popen(
        cmd,
        stdin=subprocess.PIPE,
        stdout=subprocess.DEVNULL,
    )

    # ------------------------------------------------------------------
    # Render every frame.
    # ------------------------------------------------------------------

    for i in range(n_frames):
        t = i / fps

        frame = base.copy()

        for event in _active_events(
            timeline,
            t,
        ):
            action = event["action"]

            if action == "highlight":
                _draw_highlight(
                    frame,
                    event,
                )

            elif action == "box":
                _draw_box(
                    frame,
                    event,
                )

            elif action == "underline":
                _draw_underline(
                    frame,
                    event,
                )

            elif action == "label":
                _draw_label(
                    frame,
                    event,
                )

        # RGB -> BGR for ffmpeg.
        arr = np.asarray(
            frame,
            dtype=np.uint8,
        )[:, :, ::-1]

        proc.stdin.write(
            arr.tobytes()
        )

    # ------------------------------------------------------------------
    # Finish FFmpeg.
    # ------------------------------------------------------------------

    proc.stdin.close()

    proc.wait()

    if proc.returncode != 0:
        raise RuntimeError(
            f"ffmpeg exited with code {proc.returncode}"
        )