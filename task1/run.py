#!/usr/bin/env python3
"""Task 01 pipeline entry point.

Usage:
  python run.py --image demo_input/background.png --audio demo_input/narration.wav \
      --output-dir output

Stages:
  1. transcribe  -> output/transcript.json   (word-level timestamps)
  2. layout      -> output/layout.json       (text lines, options, diagram space)
  3. plan        -> output/timeline.json     (annotation events + reasons)
  4. render      -> output/annotated_video.mp4
"""

from __future__ import annotations

import argparse
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent))

from src import layout as layout_mod
from src import plan as plan_mod
from src import render as render_mod
from src import transcribe as transcribe_mod


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--image", type=Path, required=True, help="background image")
    parser.add_argument("--audio", type=Path, required=True, help="narration audio")
    parser.add_argument("--model", type=str, default=transcribe_mod.DEFAULT_MODEL,
                        help="whisper model name (tiny/base/small)")
    parser.add_argument("--output-dir", type=Path, default=Path("output"))
    parser.add_argument("--skip-transcribe", action="store_true",
                        help="reuse existing transcript.json")
    parser.add_argument("--skip-layout", action="store_true",
                        help="reuse existing layout.json")
    parser.add_argument("--skip-plan", action="store_true",
                        help="reuse existing timeline.json")
    args = parser.parse_args()

    if not args.image.exists():
        print(f"error: image not found: {args.image}", file=sys.stderr)
        return 1
    if not args.audio.exists():
        print(f"error: audio not found: {args.audio}", file=sys.stderr)
        return 1

    out = args.output_dir
    out.mkdir(parents=True, exist_ok=True)

    if args.skip_transcribe and (out / "transcript.json").exists():
        print("stage 1: reusing transcript.json")
    else:
        print(f"stage 1: transcribing {args.audio} with model '{args.model}' ...")
        transcript = transcribe_mod.transcribe(args.audio, model_name=args.model)
        transcribe_mod.write_transcript(transcript, out / "transcript.json")

    if args.skip_layout and (out / "layout.json").exists():
        print("stage 2: reusing layout.json")
    else:
        print(f"stage 2: analysing layout of {args.image} ...")
        layout = layout_mod.analyze_layout(args.image)
        layout_mod.write_layout(layout, out / "layout.json")

    if args.skip_plan and (out / "timeline.json").exists():
        print("stage 3: reusing timeline.json")
    else:
        print("stage 3: planning annotation timeline ...")
        transcript = _load_json(out / "transcript.json")
        layout = _load_json(out / "layout.json")
        timeline = plan_mod.plan(transcript, layout)
        plan_mod.write_timeline(timeline, out / "timeline.json")
        _print_summary(timeline)

    if (out / "timeline.json").exists():
        print(f"stage 4: rendering {out / 'annotated_video.mp4'} ...")
        timeline = _load_json(out / "timeline.json")
        render_mod.render(args.image, args.audio, timeline, out / "annotated_video.mp4")
        print("done.")
        return 0

    print("error: missing intermediate outputs in stage 3", file=sys.stderr)
    return 1


def _load_json(path: Path) -> dict:
    import json

    return json.loads(path.read_text(encoding="utf-8"))


def _print_summary(timeline: dict) -> None:
    print(f"  planned {timeline['event_count']} events over {timeline['video_duration']}s")
    for e in timeline["events"]:
        print(
            f"  [{e['start']:6.2f}s] {e['action']:<10} {e.get('text','')[:48]:<48} "
            f"({e['rule']})"
        )


if __name__ == "__main__":
    sys.exit(main())
