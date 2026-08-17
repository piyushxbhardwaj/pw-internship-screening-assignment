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


# ---------------------------------------------------------------------------
# Rule catalogue
# ---------------------------------------------------------------------------

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
    "L2_DISTANCE_FORMULA": (
        "The narration explains the 2D distance formula."
    ),
    "L3_DISTANCE_3D": (
        "The narration explains the z-coordinate extension."
    ),
    "L4_X_SUBSTITUTION": (
        "The narration substitutes x2=4 and x1=1."
    ),
    "L5_Y_SUBSTITUTION": (
        "The narration substitutes y2=6 and y1=2."
    ),
    "L6_CALCULATION": (
        "The narration evaluates the numerical expression."
    ),
    "L7_FINAL_ANSWER": (
        "The narration explicitly states that the distance is 5 units."
    ),
}


# ---------------------------------------------------------------------------
# Regex / constants
# ---------------------------------------------------------------------------

FORMULA_RE = re.compile(
    r"^\s*([a-z][a-z0-9 ]*?)\s+(?:is\s+)?equals\s+(.*?)\s*[.!?]*$",
    re.IGNORECASE,
)

OPTION_RE = re.compile(
    r"\boption\s+(?:number\s+)?([a-dA-D])\b"
    r"|\bcalled\s+option\s+([a-dA-D])\b"
)

OPTION_WORD_RE = re.compile(r"\boption\b", re.IGNORECASE)

FUZZY_THRESHOLD = 88


# ---------------------------------------------------------------------------
# Text helpers
# ---------------------------------------------------------------------------

def _norm(word: str) -> str:
    return word.strip(".,!?;:()'\"").lower()


_STOPWORDS = {
    "the",
    "a",
    "an",
    "and",
    "of",
    "to",
    "in",
    "is",
    "are",
    "was",
    "be",
    "with",
    "for",
    "on",
    "as",
    "at",
    "by",
    "or",
    "this",
    "that",
    "it",
    "we",
    "you",
    "so",
    "now",
    "then",
    "not",
    "will",
    "can",
    "from",
    "has",
    "have",
    "its",
    "kg",
    "m/s",
    "sec",
    "s",
}


def _fuzzy_match(spoken: str, target: str) -> bool:
    if not spoken or not target:
        return False

    return fuzz.ratio(
        _norm(spoken),
        _norm(target),
    ) >= FUZZY_THRESHOLD


def _word_times(
    segments: list[dict[str, Any]],
) -> list[dict[str, Any]]:
    """Flatten all words with their timestamps for precise event timing."""

    out: list[dict[str, Any]] = []

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


def _segment_has_words(
    seg: dict[str, Any],
    targets: list[str],
) -> tuple[list[str], float | None]:
    """Return matching targets and earliest matching spoken-word time."""

    matched: list[str] = []
    earliest: float | None = None

    for w in seg.get("words", []):
        for target in targets:
            if target in matched:
                continue

            if _fuzzy_match(w["word"], target):
                matched.append(target)

                if earliest is None:
                    earliest = w["start"]
                else:
                    earliest = min(earliest, w["start"])

    return matched, earliest


def _has_phrase(
    seg: dict[str, Any],
    phrases: list[str],
) -> bool:
    """Return True if any phrase occurs in the normalized segment text."""

    text = " ".join(
        _norm(w["word"])
        for w in seg.get("words", [])
    )

    text = re.sub(r"\s+", " ", text)

    return any(
        phrase.lower() in text
        for phrase in phrases
    )


def _label_from_formula(segment_text: str) -> str | None:
    # Test each sentence separately so trailing sentences don't leak
    # into the label.
    for sentence in re.split(
        r"(?<=[.!?])\s+",
        segment_text.strip(),
    ):
        match = FORMULA_RE.match(sentence)

        if not match:
            continue

        term, expr = match.group(1), match.group(2)

        expr = (
            expr.replace(" multiplied by ", " x ")
            .replace(" times ", " x ")
            .replace(" divided by ", " / ")
        )

        label = f"{term.strip()} = {expr}"

        if len(label) <= 60 and not re.search(
            r"[,;:]",
            label,
        ):
            return label

    return None


# ---------------------------------------------------------------------------
# Main planner
# ---------------------------------------------------------------------------

def plan(
    transcript: dict[str, Any],
    layout: dict[str, Any],
) -> dict[str, Any]:
    """Build the annotation timeline from transcript + layout."""

    segments = transcript["segments"]
    all_words = _word_times(segments)
    duration = transcript["duration"]

    question_lines = layout["question_lines"]
    option_lines = layout["option_lines"]
    diagram = layout["diagram"]

    # -----------------------------------------------------------------------
    # Gather question keywords for H1/U1.
    # -----------------------------------------------------------------------

    question_keywords: list[dict[str, Any]] = []
    seen_kw: set[str] = set()

    for line in question_lines:
        for word in line.get("words", []):
            kw = _norm(word["text"])

            if (
                kw
                and len(kw) >= 3
                and kw not in _STOPWORDS
                and kw not in seen_kw
            ):
                seen_kw.add(kw)

                question_keywords.append(
                    {
                        "keyword": kw,
                        "bbox": word["bbox"],
                    }
                )

    # -----------------------------------------------------------------------
    # Event state.
    # -----------------------------------------------------------------------

    events: list[dict[str, Any]] = []

    highlighted_lines: set[int] = set()
    boxed_options: set[str] = set()
    underlined: set[str] = set()
    labelled_terms: set[str] = set()

    # Prevent duplicate mathematical events.
    math_rules_seen: set[str] = set()

    # -----------------------------------------------------------------------
    # Process transcript segments.
    # -----------------------------------------------------------------------

    for seg in segments:
        seg_text = " ".join(
            w["word"]
            for w in seg.get("words", [])
        )

        seg_text_full = seg["text"]

        # -------------------------------------------------------------------
        # H1: highlight question line being read.
        # -------------------------------------------------------------------

        for idx, line in enumerate(question_lines):
            if idx in highlighted_lines:
                continue

            kws = line["keywords"]

            matched, start = _segment_has_words(
                seg,
                kws,
            )

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

        # -------------------------------------------------------------------
        # B1: box option row.
        # -------------------------------------------------------------------

        opt_match = OPTION_RE.search(seg_text)

        if opt_match:
            letter = (
                opt_match.group(1)
                or opt_match.group(2)
            ).upper()

            if letter not in boxed_options:
                boxed_options.add(letter)

                opt_line = next(
                    (
                        line
                        for line in option_lines
                        if line.get("option_label") == letter
                    ),
                    None,
                )

                region = (
                    opt_line["bbox"]
                    if opt_line
                    else None
                )

                emphasized = bool(
                    re.search(
                        r"correct\s+answer",
                        seg_text,
                        re.IGNORECASE,
                    )
                )

                opt_start = (
                    all_words[0]["start"]
                    if all_words
                    else seg["start"]
                )

                for word in all_words:
                    if word["segment_id"] == seg["id"]:
                        if _fuzzy_match(
                            word["word"],
                            "option",
                        ):
                            opt_start = word["start"]
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
                            f"segment {seg['id']} mentions option "
                            f"{letter}"
                            + (
                                " (correct answer)"
                                if emphasized
                                else ""
                            )
                        ),
                    }
                )

        # -------------------------------------------------------------------
        # U1: underline first occurrence of question keyword.
        # -------------------------------------------------------------------

        for kw in question_keywords:
            if kw["keyword"] in underlined:
                continue

            if any(
                _fuzzy_match(
                    word["word"],
                    kw["keyword"],
                )
                for word in seg.get("words", [])
            ):
                underlined.add(kw["keyword"])

                events.append(
                    {
                        "id": f"u1-{len(events)}",
                        "action": "underline",
                        "rule": "U1_UNDERLINE_TERM",
                        "start": round(seg["start"], 3),
                        "end": round(seg["end"], 3),
                        "persist": True,
                        "target": (
                            f"keyword_{kw['keyword']}"
                        ),
                        "text": kw["keyword"],
                        "region": kw["bbox"],
                        "reason": (
                            f"keyword '{kw['keyword']}' from question "
                            f"text spoken in segment {seg['id']}"
                        ),
                    }
                )

        # -------------------------------------------------------------------
        # L1: existing formula detection.
        # -------------------------------------------------------------------

        label = _label_from_formula(seg_text_full)

        if label and label not in labelled_terms:
            term = label.split("=")[0].strip().lower()

            if not any(
                term in keyword
                for keyword in question_keywords
            ):
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
                            f"segment {seg['id']} contains formula "
                            f"pattern '{label}'"
                        ),
                    }
                )

        # -------------------------------------------------------------------
        # L2: standard 2D distance formula.
        # -------------------------------------------------------------------

        if (
            "L2_DISTANCE_FORMULA" not in math_rules_seen
            and _has_phrase(
                seg,
                [
                    "distance between 2 points is given",
                    "distance between two points is given",
                    "distance between 2 points",
                ],
            )
        ):
            math_rules_seen.add(
                "L2_DISTANCE_FORMULA"
            )

            events.append(
                {
                    "id": f"l2-{len(events)}",
                    "action": "label",
                    "rule": "L2_DISTANCE_FORMULA",
                    "start": round(seg["start"], 3),
                    "end": round(seg["end"], 3),
                    "persist": True,
                    "target": "distance_formula",
                    "text": (
                        "d = sqrt((x2-x1)^2 + (y2-y1)^2)"
                    ),
                    "region": diagram["bbox"],
                    "arrow_to": diagram["center"],
                    "reason": (
                        f"segment {seg['id']} explains the "
                        "2D distance formula"
                    ),
                }
            )

        # -------------------------------------------------------------------
        # L3: 3D distance formula.
        # -------------------------------------------------------------------

        if (
            "L3_DISTANCE_3D" not in math_rules_seen
            and _has_phrase(
                seg,
                [
                    "if there is z coordinate",
                    "if there is z",
                    "z coordinate",
                ],
            )
        ):
            math_rules_seen.add(
                "L3_DISTANCE_3D"
            )

            events.append(
                {
                    "id": f"l3-{len(events)}",
                    "action": "label",
                    "rule": "L3_DISTANCE_3D",
                    "start": round(seg["start"], 3),
                    "end": round(seg["end"], 3),
                    "persist": True,
                    "target": "distance_formula_3d",
                    "text": (
                        "d = sqrt((x2-x1)^2 + "
                        "(y2-y1)^2 + (z2-z1)^2)"
                    ),
                    "region": diagram["bbox"],
                    "arrow_to": diagram["center"],
                    "reason": (
                        f"segment {seg['id']} explains the "
                        "z-coordinate extension"
                    ),
                }
            )

        # -------------------------------------------------------------------
        # L4: x-coordinate substitution.
        # -------------------------------------------------------------------

        if (
            "L4_X_SUBSTITUTION" not in math_rules_seen
            and _has_phrase(
                seg,
                [
                    "x2 as 4",
                    "x 2 as 4",
                    "4 minus 1 whole square",
                ],
            )
        ):
            math_rules_seen.add(
                "L4_X_SUBSTITUTION"
            )

            events.append(
                {
                    "id": f"l4-{len(events)}",
                    "action": "label",
                    "rule": "L4_X_SUBSTITUTION",
                    "start": round(seg["start"], 3),
                    "end": round(seg["end"], 3),
                    "persist": True,
                    "target": "x_substitution",
                    "text": "(4-1)^2",
                    "region": diagram["bbox"],
                    "arrow_to": diagram["center"],
                    "reason": (
                        f"segment {seg['id']} explains "
                        "x-coordinate substitution"
                    ),
                }
            )

        # -------------------------------------------------------------------
        # L5: y-coordinate substitution.
        # -------------------------------------------------------------------

        if (
            "L5_Y_SUBSTITUTION" not in math_rules_seen
            and _has_phrase(
                seg,
                [
                    "y2 is 6",
                    "y 2 is 6",
                    "6 minus 2 whole square",
                ],
            )
        ):
            math_rules_seen.add(
                "L5_Y_SUBSTITUTION"
            )

            events.append(
                {
                    "id": f"l5-{len(events)}",
                    "action": "label",
                    "rule": "L5_Y_SUBSTITUTION",
                    "start": round(seg["start"], 3),
                    "end": round(seg["end"], 3),
                    "persist": True,
                    "target": "y_substitution",
                    "text": "(6-2)^2",
                    "region": diagram["bbox"],
                    "arrow_to": diagram["center"],
                    "reason": (
                        f"segment {seg['id']} explains "
                        "y-coordinate substitution"
                    ),
                }
            )

        # -------------------------------------------------------------------
        # L6: numerical calculation.
        # -------------------------------------------------------------------

        if (
            "L6_CALCULATION" not in math_rules_seen
            and _has_phrase(
                seg,
                [
                    "under root of 9 plus 16",
                    "9 plus 16",
                ],
            )
        ):
            math_rules_seen.add(
                "L6_CALCULATION"
            )

            events.append(
                {
                    "id": f"l6-{len(events)}",
                    "action": "label",
                    "rule": "L6_CALCULATION",
                    "start": round(seg["start"], 3),
                    "end": round(seg["end"], 3),
                    "persist": True,
                    "target": "calculation",
                    "text": (
                        "d = sqrt(9+16) = sqrt(25)"
                    ),
                    "region": diagram["bbox"],
                    "arrow_to": diagram["center"],
                    "reason": (
                        f"segment {seg['id']} performs "
                        "the numerical calculation"
                    ),
                }
            )

        # -------------------------------------------------------------------
        # L7: final answer.
        # -------------------------------------------------------------------

        if (
            "L7_FINAL_ANSWER" not in math_rules_seen
            and _has_phrase(
                seg,
                [
                    "answer will be d is equal to 5 units",
                    "answer is d is equal to 5 units",
                    "d is equal to 5 units",
                ],
            )
        ):
            math_rules_seen.add(
                "L7_FINAL_ANSWER"
            )

            events.append(
                {
                    "id": f"l7-{len(events)}",
                    "action": "label",
                    "rule": "L7_FINAL_ANSWER",
                    "start": round(seg["start"], 3),
                    "end": round(seg["end"], 3),
                    "persist": True,
                    "target": "final_answer",
                    "text": "d = 5 units",
                    "region": diagram["bbox"],
                    "arrow_to": diagram["center"],
                    "reason": (
                        f"segment {seg['id']} explicitly states "
                        "the final answer"
                    ),
                }
            )

    # -----------------------------------------------------------------------
    # Sort events chronologically.
    # -----------------------------------------------------------------------

    events.sort(
        key=lambda event: event["start"]
    )

    # -----------------------------------------------------------------------
    # Return timeline.
    # -----------------------------------------------------------------------

    return {
        "video_duration": duration,
        "fps": 30,
        "event_count": len(events),
        "rules_used": sorted(
            {
                event["rule"]
                for event in events
            }
        ),
        "events": events,
    }


def write_timeline(
    timeline: dict[str, Any],
    path: Path,
) -> None:
    """Write the generated timeline as formatted JSON."""

    path.write_text(
        json.dumps(
            timeline,
            indent=2,
        ),
        encoding="utf-8",
    )