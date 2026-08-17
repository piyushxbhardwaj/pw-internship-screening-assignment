#!/usr/bin/env python3
"""Generate a clearly-labelled SYNTHETIC demo input pair for the Task 01 pipeline.

IMPORTANT: The background image and narration produced here are NOT the
official PW assignment inputs. They exist only so the pipeline can be
developed, tested and demonstrated end-to-end before the real background
image + narration audio are provided. The pipeline itself reads any image and
any audio file, so the real inputs can replace demo_input/ without changing
any pipeline code.

Outputs (in task1/demo_input/):
  background.png   1280x720 physics question + diagram space
  narration.txt    the teacher narration script used to drive TTS
  narration.wav    synthesized teacher narration (piper neural TTS)
"""

from __future__ import annotations

import argparse
import json
import sys
from pathlib import Path

from PIL import Image, ImageDraw, ImageFont

ROOT = Path(__file__).resolve().parents[1]

FONT_DIR = Path("/usr/share/fonts/truetype/dejavu")
REGULAR_FONT = FONT_DIR / "DejaVuSans.ttf"
BOLD_FONT = FONT_DIR / "DejaVuSans-Bold.ttf"

WIDTH, HEIGHT = 1280, 720

NARRATION = (
    "Welcome students. Today we will solve a numerical problem from physics. "
    "Let us read the question carefully. "
    "A body of mass five kilograms is moving with a velocity of ten meters per second. "
    "Find the momentum of the body. "
    "Now to solve this problem, we recall the formula. "
    "Momentum equals mass times velocity. "
    "Substituting the values, momentum equals five multiplied by ten. "
    "So the momentum is fifty kilogram meters per second. "
    "Now look at the options. "
    "Option A is ten kilogram meters per second. "
    "Option B is twenty kilogram meters per second. "
    "Option C is fifty kilogram meters per second. "
    "Option D is one hundred kilogram meters per second. "
    "Since the momentum is fifty kilogram meters per second, "
    "the correct answer is option C. "
    "Therefore, option C is the correct answer."
)

QUESTION_LINES = [
    "A body of mass 5 kg is moving with a velocity of 10 m/s.",
    "Find the momentum of the body.",
]

OPTIONS = [
    ("A", "10 kg m/s"),
    ("B", "20 kg m/s"),
    ("C", "50 kg m/s"),
    ("D", "100 kg m/s"),
]


def _font(size: int, bold: bool = False) -> ImageFont.FreeTypeFont:
    return ImageFont.truetype(str(BOLD_FONT if bold else REGULAR_FONT), size)


def make_background() -> Image.Image:
    img = Image.new("RGB", (WIDTH, HEIGHT), "white")
    d = ImageDraw.Draw(img)

    # Thin page border
    d.rectangle([10, 10, WIDTH - 10, HEIGHT - 10], outline="#c9d2e0", width=2)

    # Header bar
    d.rectangle([0, 0, WIDTH, 64], fill="#0b2a6b")
    d.text((40, 18), "Physics  |  Numerical Practice  |  Momentum",
           font=_font(24, bold=True), fill="white")

    # Question block (left column)
    qx = 70
    d.text((qx, 96), "Q. " + QUESTION_LINES[0], font=_font(26, bold=True), fill="#111111")
    d.text((qx, 140), "    " + QUESTION_LINES[1], font=_font(26, bold=True), fill="#111111")

    # Options (left column)
    opt_y = 240
    for label, text in OPTIONS:
        d.text((qx, opt_y), f"{label})  {text}", font=_font(24), fill="#222222")
        opt_y += 56

    # Diagram space (right column): bordered blank area + caption ABOVE the border
    box = (720, 96, 1230, 560)
    d.rectangle(box, outline="#0b2a6b", width=3)
    d.rectangle([box[0] + 4, box[1] + 4, box[2] - 4, box[3] - 4], outline="#d9e2f2", width=1)
    d.text((box[0], box[1] - 34), "Diagram Space", font=_font(20, bold=True), fill="#445566")

    # Footer disclaimer (labels the input as synthetic)
    d.text((40, HEIGHT - 46), "SYNTHETIC DEMO INPUT — not the official PW assignment asset.",
           font=_font(16), fill="#778899")

    return img


def make_audio(out_wav: Path, voice: str = "en_US-lessac-medium") -> None:
    from piper import PiperVoice

    voices_dir = ROOT / "demo_input" / "voices"
    model_path = voices_dir / f"{voice}.onnx"
    if not model_path.exists():
        from piper.download_voices import download_voice

        download_voice(voice, voices_dir)

    import wave

    voice_model = PiperVoice.load(str(model_path))
    with wave.open(str(out_wav), "wb") as wav_file:
        voice_model.synthesize_wav(NARRATION, wav_file)
    print(f"audio written: {out_wav}")


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--out-dir", type=Path, default=ROOT / "demo_input")
    parser.add_argument("--skip-tts", action="store_true",
                        help="regenerate only the image + script, reuse existing narration.wav")
    args = parser.parse_args()

    args.out_dir.mkdir(parents=True, exist_ok=True)

    bg = make_background()
    bg_path = args.out_dir / "background.png"
    bg.save(bg_path)
    print(f"background written: {bg_path}")

    script_path = args.out_dir / "narration.txt"
    script_path.write_text(NARRATION, encoding="utf-8")
    print(f"script written: {script_path}")

    wav_path = args.out_dir / "narration.wav"
    if not args.skip_tts or not wav_path.exists():
        make_audio(wav_path)
    else:
        print(f"audio reused (--skip-tts): {wav_path}")

    meta = {
        "label": "SYNTHETIC DEMO INPUT - NOT the official PW assignment asset",
        "generator": str(Path(__file__).name),
        "image": str(bg_path.relative_to(ROOT)),
        "narration_script": str(script_path.relative_to(ROOT)),
        "narration_audio": str(wav_path.relative_to(ROOT)),
        "script_text": NARRATION,
    }
    (args.out_dir / "manifest.json").write_text(json.dumps(meta, indent=2), encoding="utf-8")
    print(f"manifest written: {args.out_dir / 'manifest.json'}")
    return 0


if __name__ == "__main__":
    sys.exit(main())
