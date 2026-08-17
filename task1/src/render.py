"""Frame rendering + ffmpeg muxing.

Draws the background image each frame with every annotation event whose start
time has been reached (annotations persist once they appear), then pipes raw
BGR frames into ffmpeg together with the narration audio to produce an MP4.
"""

from __future__ import annotations

import subprocess
from pathlib import Path
from typing import Any

import numpy as np
from PIL import Image, ImageDraw, ImageFont

FONT_DIR = Path("/usr/share/fonts/truetype/dejavu")
LABEL_FONT = str(FONT_DIR / "DejaVuSans-Bold.ttf")

COLORS = {
    "highlight": (255, 213, 79, 100),   # translucent yellow
    "box": (220, 53, 69, 255),          # red
    "box_emph": (9, 105, 218, 255),     # stronger blue when emphasised
    "underline": (9, 105, 218, 255),
    "label_bg": (11, 42, 107, 255),
    "label_text": (255, 255, 255, 255),
    "arrow": (11, 42, 107, 255),
}


def _active_events(timeline: dict[str, Any], t: float) -> list[dict[str, Any]]:
    out = []
    for e in timeline["events"]:
        if e["start"] <= t:
            out.append(e)
    # Layer order so strokes sit on top of translucent fills.
    out.sort(key=lambda e: _LAYER_ORDER.get(e["action"], 10))
    return out


_LAYER_ORDER = {"highlight": 0, "underline": 1, "box": 2, "label": 3}


def _draw_highlight(base: Image.Image, event: dict[str, Any]) -> None:
    x1, y1, x2, y2 = event["region"]
    overlay = Image.new("RGBA", base.size, (0, 0, 0, 0))
    d = ImageDraw.Draw(overlay)
    d.rectangle([x1 - 6, y1 - 3, x2 + 6, y2 + 6], fill=COLORS["highlight"])
    base.paste(Image.alpha_composite(base.convert("RGBA"), overlay), (0, 0))


def _draw_box(base: Image.Image, event: dict[str, Any]) -> None:
    if not event["region"]:
        return
    x1, y1, x2, y2 = event["region"]
    color = COLORS["box_emph"] if event.get("emphasized") else COLORS["box"]
    width = 6 if event.get("emphasized") else 4
    d = ImageDraw.Draw(base)
    d.rectangle([x1 - 8, y1 - 6, x2 + 8, y2 + 8], outline=color, width=width)


def _draw_underline(base: Image.Image, event: dict[str, Any]) -> None:
    x1, y1, x2, y2 = event["region"]
    d = ImageDraw.Draw(base)
    d.line([(x1, y2 + 3), (x2, y2 + 3)], fill=COLORS["underline"], width=4)


def _draw_label(base: Image.Image, event: dict[str, Any], font_size: int = 26) -> None:
    d = ImageDraw.Draw(base)
    font = ImageFont.truetype(LABEL_FONT, font_size)
    text = event["text"]
    box_w = d.textlength(text, font=font) + 24
    box_h = font_size + 20

    x1, y1, _, _ = event["region"]
    # Place the badge at the top-left inside the diagram space.
    bx, by = x1 + 12, y1 + 12
    if bx + box_w > base.size[0] - 8:
        bx = base.size[0] - box_w - 8
    if by + box_h > base.size[1] - 8:
        by = base.size[1] - box_h - 8

    d.rounded_rectangle([bx, by, bx + box_w, by + box_h], radius=8, fill=COLORS["label_bg"])
    d.text((bx + 12, by + 10), text, font=font, fill=COLORS["label_text"])

    # Arrow from the badge to the diagram centre.
    cx, cy = event["arrow_to"]
    ax = bx + box_w // 2
    ay = by + box_h
    d.line([(ax, ay), (cx, cy)], fill=COLORS["arrow"], width=3)
    # Arrowhead.
    import math

    ang = math.atan2(cy - ay, cx - ax)
    for da in (-0.5, 0.5):
        tip = (cx - 14 * math.cos(ang + da), cy - 14 * math.sin(ang + da))
        d.line([(cx, cy), tip], fill=COLORS["arrow"], width=3)


def render(
    background_path: Path,
    audio_path: Path,
    timeline: dict[str, Any],
    output_path: Path,
) -> None:
    """Render annotated frames and mux with audio into an MP4."""
    fps = timeline.get("fps", 30)
    duration = timeline["video_duration"]
    n_frames = int(round(duration * fps))

    base = Image.open(background_path).convert("RGB")
    w, h = base.size

    cmd = [
        "ffmpeg",
        "-y",
        "-loglevel", "error",
        "-f", "rawvideo",
        "-pix_fmt", "bgr24",
        "-s", f"{w}x{h}",
        "-r", str(fps),
        "-i", "-",                      # frames from stdin
        "-i", str(audio_path),          # narration audio
        "-c:v", "libx264",
        "-preset", "veryfast",
        "-crf", "23",
        "-pix_fmt", "yuv420p",
        "-c:a", "aac",
        "-shortest",
        "-movflags", "+faststart",
        str(output_path),
    ]

    proc = subprocess.Popen(cmd, stdin=subprocess.PIPE, stdout=subprocess.DEVNULL)

    for i in range(n_frames):
        t = i / fps
        frame = base.copy()
        for event in _active_events(timeline, t):
            if event["action"] == "highlight":
                _draw_highlight(frame, event)
            elif event["action"] == "box":
                _draw_box(frame, event)
            elif event["action"] == "underline":
                _draw_underline(frame, event)
            elif event["action"] == "label":
                _draw_label(frame, event)

        arr = np.asarray(frame, dtype=np.uint8)[:, :, ::-1]  # RGB -> BGR
        proc.stdin.write(arr.tobytes())

    proc.stdin.close()
    proc.wait()
    if proc.returncode != 0:
        raise RuntimeError(f"ffmpeg exited with code {proc.returncode}")
