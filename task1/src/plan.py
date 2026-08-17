"""Deterministic annotation planning.

Maps the transcript + layout onto a timeline of annotation events using a small
table of explicit rules. No LLM is involved: every event carries a `rule` id
and a human-readable `reason` so decisions are auditable.

Event actions:
  highlight : translucent yellow band behind a question-text line
  box       : rectangle around an option row (emphasis = "correct answer")
  underline : line under a keyword's word-box inside a question line
  label     : term badge drawn in the diagram space + arrow to its centre
"""

from __future__ import annotations

import json
import re
from pathlib import Path
from typing import Any

from rapidfuzz import fuzz

# Rule catalogue (documentation table used in README).
RULES = {
    "H1_HIGHLIGHT_QUESTION": (
        "A spoken segment fuzzy-matches >= 2 keywords of a question-text line; "
        "highlight that line while it is being read."
    ),
    "B1_BOX_OPTION": (
        "The teacher says 'option <letter>' (optionally 'number <letter>'); "
        "box that option row. If 'correct answer' is also spoken in the same "
        "segment, the box is emphasised."
    ),
    "U1_UNDERLINE_TERM": (
        "A keyword that appears in a question-text line is spoken for the "
        "first time; underline that word's position in the question."
    ),
    "L1_LABEL_FORMULA": (
        "A spoken segment contains a formula pattern '<term> equals <expr>' "
        "(or 'multiplied by'/'times'); place the term as a label in the "
        "diagram space with an arrow to its centre."
    ),
}

FORMULA_RE = re.compile(
    r"^\s*([a-z][a-z0-9 ]*?)\s+(?:is\s+)?equals\s+(.*?)\s*[.!?]*$",
    re.IGNORECASE,
)
OPTION_RE = re.compile(
    r"\boption\s+(?:number\s+)?([a-dA-D])\b|\bcalled\s+option\s+([a-dA-D])\b"
)
OPTION_WORD_RE = re.compile(r"\boption\b", re.IGNORECASE)

FUZZY_THRESHOLD = 88


def _norm(word: str) -> str:
    return word.strip(".,!?;:()'\"").lower()


_STOPWORDS = {
    "the", "a", "an", "and", "of", "to", "in", "is", "are", "was", "be",
    "with", "for", "on", "as", "at", "by", "or", "this", "that", "it",
    "we", "you", "so", "now", "then", "not", "will", "can", "from",
    "has", "have", "its", "kg", "m/s", "sec", "s",
}


def _fuzzy_match(spoken: str, target: str) -> bool:
    if not spoken or not target:
        return False
    return fuzz.ratio(_norm(spoken), _norm(target)) >= FUZZY_THRESHOLD


def _word_times(segments: list[dict[str, Any]]) -> list[dict[str, Any]]:
    """Flatten all words with their timestamps for precise event timing."""
    out = []
    for seg in segments:
        for w in seg.get("words", []):
            out.append(
                {
                    "word": _norm(w["word"]),
                    "start": w["start"],
                    "end": w["end"],
                    "segment_id": seg["id"],
                }
            )
    return out


def _segment_has_words(seg: dict[str, Any], targets: list[str]) -> tuple[list[str], float | None]:
    """Return the subset of `targets` fuzzy-present in a segment, and the time
    of the earliest matching spoken word."""
    matched: list[str] = []
    earliest: float | None = None
    for w in seg.get("words", []):
        for t in targets:
            if t in matched:
                continue
            if _fuzzy_match(w["word"], t):
                matched.append(t)
                earliest = w["start"] if earliest is None else min(earliest, w["start"])
    return matched, earliest


def _label_from_formula(segment_text: str) -> str | None:
    import re as _re

    # Test each sentence separately so trailing sentences don't leak into the label.
    for sentence in _re.split(r"(?<=[.!?])\s+", segment_text.strip()):
        m = FORMULA_RE.match(sentence)
        if not m:
            continue
        term, expr = m.group(1), m.group(2)
        expr = (
            expr.replace(" multiplied by ", " x ")
            .replace(" times ", " x ")
            .replace(" divided by ", " / ")
        )
        label = f"{term.strip()} = {expr}"
        if len(label) <= 60 and not _re.search(r"[,;:]", label):
            return label
    return None


def plan(transcript: dict[str, Any], layout: dict[str, Any]) -> dict[str, Any]:
    """Build the annotation timeline from transcript + layout."""
    segments = transcript["segments"]
    all_words = _word_times(segments)
    duration = transcript["duration"]

    question_lines = layout["question_lines"]
    option_lines = layout["option_lines"]
    diagram = layout["diagram"]

    # Gather all question keywords (with word-boxes for underline targets).
    question_keywords: list[dict[str, Any]] = []
    seen_kw: set[str] = set()
    for line in question_lines:
        for w in line.get("words", []):
            kw = _norm(w["text"])
            if (
                kw
                and len(kw) >= 3
                and kw not in _STOPWORDS
                and kw not in seen_kw
            ):
                seen_kw.add(kw)
                question_keywords.append({"keyword": kw, "bbox": w["bbox"]})

    events: list[dict[str, Any]] = []
    highlighted_lines: set[int] = set()
    boxed_options: set[str] = set()
    underlined: set[str] = set()
    labelled_terms: set[str] = set()

    for seg in segments:
        seg_text = " ".join(w["word"] for w in seg.get("words", []))
        seg_text_full = seg["text"]

        # --- H1: highlight question line being read --------------------------
        for idx, line in enumerate(question_lines):
            if idx in highlighted_lines:
                continue
            kws = line["keywords"]
            matched, start = _segment_has_words(seg, kws)
            if len(matched) >= 2 and start is not None:
                highlighted_lines.add(idx)
                events.append(
                    {
                        "id": f"h1-{len(events)}",
                        "action": "highlight",
                        "rule": "H1_HIGHLIGHT_QUESTION",
                        "start": round(start, 3),
                        "end": round(seg["end"], 3),
                        "persist": True,
                        "target": f"question_line_{idx}",
                        "text": line["text"],
                        "region": line["bbox"],
                        "reason": (
                            f"segment {seg['id']} fuzzy-matched keywords "
                            f"{matched} of question line {idx}"
                        ),
                    }
                )

        # --- B1: box option row ----------------------------------------------
        opt_m = OPTION_RE.search(seg_text)
        if opt_m:
            letter = (opt_m.group(1) or opt_m.group(2)).upper()
            if letter not in boxed_options:
                boxed_options.add(letter)
                opt_line = next(
                    (l for l in option_lines if l.get("option_label") == letter), None
                )
                region = opt_line["bbox"] if opt_line else None
                emphasized = bool(re.search(r"correct\s+answer", seg_text, re.I))
                opt_start = all_words[0]["start"] if all_words else seg["start"]
                for w in all_words:
                    if w["segment_id"] == seg["id"] and _fuzzy_match(w["word"], "option"):
                        opt_start = w["start"]
                        break
                events.append(
                    {
                        "id": f"b1-{len(events)}",
                        "action": "box",
                        "rule": "B1_BOX_OPTION",
                        "start": round(opt_start, 3),
                        "end": round(seg["end"], 3),
                        "persist": True,
                        "emphasized": emphasized,
                        "target": f"option_{letter}",
                        "text": f"Option {letter}",
                        "region": region,
                        "reason": (
                            f"segment {seg['id']} mentions option {letter}"
                            + (" (correct answer)" if emphasized else "")
                        ),
                    }
                )

        # --- U1: underline first occurrence of a question keyword ------------
        for kw in question_keywords:
            if kw["keyword"] in underlined:
                continue
            if any(_fuzzy_match(w["word"], kw["keyword"]) for w in seg.get("words", [])):
                underlined.add(kw["keyword"])
                events.append(
                    {
                        "id": f"u1-{len(events)}",
                        "action": "underline",
                        "rule": "U1_UNDERLINE_TERM",
                        "start": round(seg["start"], 3),
                        "end": round(seg["end"], 3),
                        "persist": True,
                        "target": f"keyword_{kw['keyword']}",
                        "text": kw["keyword"],
                        "region": kw["bbox"],
                        "reason": (
                            f"keyword '{kw['keyword']}' from question text spoken "
                            f"in segment {seg['id']}"
                        ),
                    }
                )

        # --- L1: label a formula term into the diagram space ------------------
        label = _label_from_formula(seg_text_full)
        if label and label not in labelled_terms:
            term = label.split("=")[0].strip().lower()
            if not any(term in k for k in question_keywords):  # not already on the page
                labelled_terms.add(label)
                events.append(
                    {
                        "id": f"l1-{len(events)}",
                        "action": "label",
                        "rule": "L1_LABEL_FORMULA",
                        "start": round(seg["start"], 3),
                        "end": round(seg["end"], 3),
                        "persist": True,
                        "target": f"label_{term}",
                        "text": label,
                        "region": diagram["bbox"],
                        "arrow_to": diagram["center"],
                        "reason": (
                            f"segment {seg['id']} contains formula pattern "
                            f"'{label}'"
                        ),
                    }
                )

    events.sort(key=lambda e: e["start"])

    return {
        "video_duration": duration,
        "fps": 30,
        "event_count": len(events),
        "rules_used": sorted({e["rule"] for e in events}),
        "events": events,
    }


def write_timeline(timeline: dict[str, Any], path: Path) -> None:
    path.write_text(json.dumps(timeline, indent=2), encoding="utf-8")
