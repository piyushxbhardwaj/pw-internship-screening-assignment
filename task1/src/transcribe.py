"""ASR transcription with word-level timestamps (faster-whisper)."""

from __future__ import annotations

import json
from pathlib import Path
from typing import Any

from faster_whisper import WhisperModel

DEFAULT_MODEL = "tiny"


def transcribe(audio_path: Path, model_name: str = DEFAULT_MODEL) -> dict[str, Any]:
    """Transcribe audio to segments with word-level timestamps.

    Returns a transcript dict:
    {
      "model": "...",
      "language": "en",
      "duration": 46.0,
      "segments": [{"id":0, "start":.., "end":.., "text":"..",
                    "words":[{"word":"..","start":..,"end":..}]}, ...]
    }
    """
    model = WhisperModel(model_name, device="cpu", compute_type="int8")
    segments, info = model.transcribe(
        str(audio_path),
        word_timestamps=True,
        vad_filter=True,
    )

    seg_list: list[dict[str, Any]] = []
    for i, seg in enumerate(segments):
        words = [
            {"word": w.word.strip(), "start": round(w.start, 3), "end": round(w.end, 3)}
            for w in (seg.words or [])
        ]
        seg_list.append(
            {
                "id": i,
                "start": round(seg.start, 3),
                "end": round(seg.end, 3),
                "text": seg.text.strip(),
                "words": words,
            }
        )

    return {
        "model": model_name,
        "language": info.language,
        "duration": round(info.duration, 3),
        "segments": seg_list,
    }


def write_transcript(transcript: dict[str, Any], path: Path) -> None:
    path.write_text(json.dumps(transcript, indent=2), encoding="utf-8")
