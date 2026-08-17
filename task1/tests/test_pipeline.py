"""Unit tests for the Task 01 annotation pipeline.

Run from task1/ with:  python -m pytest tests -q
"""

from __future__ import annotations

import json
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))

from src import layout as layout_mod
from src import plan as plan_mod
from src import transcribe as transcribe_mod


def _sample_transcript() -> dict:
    return {
        "model": "tiny",
        "language": "en",
        "duration": 46.0,
        "segments": [
            {
                "id": 0,
                "start": 4.34,
                "end": 10.98,
                "text": "Let us read the question carefully. A body of mass "
                        "5 kilograms is moving with the velocity of 10 meters "
                        "per second.",
                "words": [
                    {"word": "A", "start": 4.4, "end": 4.5},
                    {"word": "body", "start": 4.5, "end": 4.8},
                    {"word": "of", "start": 4.8, "end": 4.9},
                    {"word": "mass", "start": 4.9, "end": 5.2},
                    {"word": "is", "start": 5.2, "end": 5.3},
                    {"word": "moving", "start": 5.3, "end": 5.7},
                    {"word": "with", "start": 5.7, "end": 5.9},
                    {"word": "the", "start": 5.9, "end": 6.0},
                    {"word": "velocity", "start": 6.0, "end": 6.4},
                ],
            },
            {
                "id": 1,
                "start": 11.14,
                "end": 15.34,
                "text": "Find the momentum of the body.",
                "words": [
                    {"word": "Find", "start": 11.2, "end": 11.5},
                    {"word": "the", "start": 11.5, "end": 11.6},
                    {"word": "momentum", "start": 11.6, "end": 12.1},
                    {"word": "of", "start": 12.1, "end": 12.2},
                    {"word": "the", "start": 12.2, "end": 12.3},
                    {"word": "body", "start": 12.3, "end": 12.7},
                ],
            },
            {
                "id": 2,
                "start": 15.64,
                "end": 19.38,
                "text": "Momentum equals mass times velocity.",
                "words": [
                    {"word": "Momentum", "start": 15.7, "end": 16.2},
                    {"word": "equals", "start": 16.2, "end": 16.6},
                    {"word": "mass", "start": 16.6, "end": 16.9},
                    {"word": "times", "start": 16.9, "end": 17.1},
                    {"word": "velocity", "start": 17.1, "end": 17.6},
                ],
            },
            {
                "id": 3,
                "start": 38.02,
                "end": 43.66,
                "text": "the correct answer is option C.",
                "words": [
                    {"word": "the", "start": 38.0, "end": 38.1},
                    {"word": "correct", "start": 38.1, "end": 38.4},
                    {"word": "answer", "start": 38.4, "end": 38.7},
                    {"word": "is", "start": 38.7, "end": 38.8},
                    {"word": "option", "start": 38.8, "end": 39.1},
                    {"word": "C", "start": 39.1, "end": 39.3},
                ],
            },
        ],
    }


def _sample_layout() -> dict:
    return {
        "image_size": [1280, 720],
        "diagram": {"bbox": [720, 96, 1230, 560], "center": [975, 328]},
        "question_lines": [
            {
                "text": "Q. A body of mass 5 kg is moving with a velocity of 10 m/s.",
                "bbox": [71, 101, 708, 126],
                "conf": 92,
                "words": [
                    {"text": "body", "bbox": [142, 101, 211, 126]},
                    {"text": "mass", "bbox": [262, 107, 334, 121]},
                    {"text": "moving", "bbox": [452, 101, 556, 126]},
                    {"text": "velocity", "bbox": [600, 101, 690, 121]},
                ],
                "kind": "question",
                "option_label": None,
                "keywords": ["body", "mass", "moving", "velocity"],
            },
            {
                "text": "Find the momentum of the body.",
                "bbox": [108, 145, 584, 170],
                "conf": 95,
                "words": [
                    {"text": "Find", "bbox": [108, 145, 168, 165]},
                    {"text": "momentum", "bbox": [239, 147, 401, 165]},
                    {"text": "body", "bbox": [510, 145, 584, 170]},
                ],
                "kind": "question",
                "option_label": None,
                "keywords": ["find", "momentum", "body"],
            },
        ],
        "option_lines": [
            {
                "text": "C) 50 kg m/s",
                "bbox": [71, 357, 229, 380],
                "conf": 91,
                "words": [],
                "kind": "option",
                "option_label": "C",
                "keywords": [],
            }
        ],
        "other_lines": [],
    }


class TestPlan:
    def test_highlight_on_keyword_match(self):
        tl = plan_mod.plan(_sample_transcript(), _sample_layout())
        highlights = [e for e in tl["events"] if e["action"] == "highlight"]
        assert len(highlights) == 2
        assert highlights[0]["start"] < highlights[1]["start"]
        assert all(e["rule"] == "H1_HIGHLIGHT_QUESTION" for e in highlights)

    def test_box_on_option_mention(self):
        tl = plan_mod.plan(_sample_transcript(), _sample_layout())
        boxes = [e for e in tl["events"] if e["action"] == "box"]
        assert len(boxes) == 1
        assert boxes[0]["target"] == "option_C"
        assert boxes[0]["emphasized"] is True
        assert boxes[0]["region"] == [71, 357, 229, 380]

    def test_label_from_formula(self):
        tl = plan_mod.plan(_sample_transcript(), _sample_layout())
        labels = [e for e in tl["events"] if e["action"] == "label"]
        assert len(labels) == 1
        assert labels[0]["text"] == "Momentum = mass x velocity"
        assert labels[0]["rule"] == "L1_LABEL_FORMULA"
        assert labels[0]["arrow_to"] == [975, 328]

    def test_no_stopword_underlines(self):
        tl = plan_mod.plan(_sample_transcript(), _sample_layout())
        underlines = [e for e in tl["events"] if e["action"] == "underline"]
        texts = {e["text"].lower() for e in underlines}
        assert "with" not in texts
        assert "the" not in texts
        assert "body" in texts or "mass" in texts

    def test_events_sorted_and_persistent(self):
        tl = plan_mod.plan(_sample_transcript(), _sample_layout())
        starts = [e["start"] for e in tl["events"]]
        assert starts == sorted(starts)
        assert all(e["persist"] is True for e in tl["events"])
        assert all("reason" in e and "rule" in e for e in tl["events"])

    def test_label_deduped(self):
        # Running twice with same transcript+layout must not duplicate labels.
        tl1 = plan_mod.plan(_sample_transcript(), _sample_layout())
        tl2 = plan_mod.plan(_sample_transcript(), _sample_layout())
        assert tl1["event_count"] == tl2["event_count"]


class TestLayout:
    def test_layout_on_demo_image(self):
        img = ROOT / "demo_input" / "background.png"
        if not img.exists():
            return
        layout = layout_mod.analyze_layout(img)
        assert layout["image_size"] == [1280, 720]
        assert len(layout["question_lines"]) >= 2
        labels = {l.get("option_label") for l in layout["option_lines"]}
        assert {"A", "B", "C", "D"} <= labels
        assert len(layout["diagram"]["bbox"]) == 4


class TestTranscribe:
    def test_transcribe_demo_audio(self):
        audio = ROOT / "demo_input" / "narration.wav"
        if not audio.exists():
            return
        transcript = transcribe_mod.transcribe(audio, model_name="tiny")
        assert transcript["language"] == "en"
        assert transcript["duration"] > 30
        texts = " ".join(s["text"] for s in transcript["segments"]).lower()
        assert "momentum" in texts
        assert any(s["words"] for s in transcript["segments"])
