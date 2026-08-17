"""Layout analysis of the background image.

Uses Tesseract OCR to locate question-text lines and option rows, and a
grid-density heuristic to find the diagram space (the largest text-free area).
"""

from __future__ import annotations

import json
import re
from pathlib import Path
from typing import Any

import cv2
import numpy as np
import pytesseract

QUESTION_MARKERS = ("q.", "ques", "question", "find", "calculate", "compute", "determine")
OPTION_RE = re.compile(r"^\s*\(?([a-dA-D])\)?\s*")

STOPWORDS = {
    "the", "a", "an", "of", "is", "are", "in", "on", "to", "for", "and",
    "or", "with", "by", "at", "from", "as", "that", "this", "be", "kg",
    "m", "s", "m/s", "per", "sec", "secs",
}


def _line_grouping(data: dict[str, Any]) -> list[dict[str, Any]]:
    """Group OCR word boxes into lines by block/paragraph/line number."""
    grouped: dict[tuple[int, int, int], list[dict[str, Any]]] = {}
    for i in range(len(data["text"])):
        text = (data["text"][i] or "").strip()
        conf = float(data["conf"][i])
        if not text or conf < 40:
            continue
        key = (data["block_num"][i], data["par_num"][i], data["line_num"][i])
        grouped.setdefault(key, []).append(
            {
                "text": text,
                "bbox": [
                    data["left"][i],
                    data["top"][i],
                    data["left"][i] + data["width"][i],
                    data["top"][i] + data["height"][i],
                ],
                "conf": conf,
            }
        )

    lines = []
    for key, words in grouped.items():
        words.sort(key=lambda w: w["bbox"][0])
        x1 = min(w["bbox"][0] for w in words)
        y1 = min(w["bbox"][1] for w in words)
        x2 = max(w["bbox"][2] for w in words)
        y2 = max(w["bbox"][3] for w in words)
        lines.append(
            {
                "text": " ".join(w["text"] for w in words),
                "bbox": [x1, y1, x2, y2],
                "conf": min(w["conf"] for w in words),
                "words": words,
            }
        )
    lines.sort(key=lambda l: (l["bbox"][1], l["bbox"][0]))
    return lines


def _diagram_region(img: np.ndarray, ocr_lines: list[dict[str, Any]]) -> dict[str, Any]:
    """Find the diagram space: the largest text-free cell block.

    Divides the image into a grid and picks the largest connected cluster of
    empty cells (cells with no OCR words inside). Falls back to the bottom-right
    quadrant if no empty area is found.
    """
    h, w = img.shape[:2]
    grid_r, grid_c = 4, 4
    cell_h, cell_w = h // grid_r, w // grid_c

    occupied = [[False] * grid_c for _ in range(grid_r)]
    for line in ocr_lines:
        x1, y1, x2, y2 = line["bbox"]
        r = range(max(0, y1 // cell_h), min(grid_r, y2 // cell_h + 1))
        c = range(max(0, x1 // cell_w), min(grid_c, x2 // cell_w + 1))
        for ri in r:
            for ci in c:
                occupied[ri][ci] = True

    # Keep header band (row 0) and footer occupied to avoid picking them.
    for ci in range(grid_c):
        occupied[0][ci] = True
        occupied[grid_r - 1][ci] = True

    best: list[tuple[int, int]] = []
    seen = set()
    for r0 in range(grid_r):
        for c0 in range(grid_c):
            if occupied[r0][c0] or (r0, c0) in seen:
                continue
            cluster: list[tuple[int, int]] = []
            stack = [(r0, c0)]
            while stack:
                r, c = stack.pop()
                if (r, c) in seen or occupied[r][c]:
                    continue
                seen.add((r, c))
                cluster.append((r, c))
                for dr, dc in ((-1, 0), (1, 0), (0, -1), (0, 1)):
                    nr, nc = r + dr, c + dc
                    if 0 <= nr < grid_r and 0 <= nc < grid_c:
                        stack.append((nr, nc))
            if len(cluster) > len(best):
                best = cluster

    if not best:
        x1, y1 = int(w * 0.55), int(h * 0.2)
        x2, y2 = int(w * 0.98), int(h * 0.9)
    else:
        rs = [r for r, _ in best]
        cs = [c for _, c in best]
        x1 = min(cs) * cell_w + 8
        y1 = min(rs) * cell_h + 8
        x2 = (max(cs) + 1) * cell_w - 8
        y2 = (max(rs) + 1) * cell_h - 8

    return {"bbox": [x1, y1, x2, y2], "center": [(x1 + x2) // 2, (y1 + y2) // 2]}


def _classify(lines: list[dict[str, Any]]) -> dict[str, Any]:
    """Tag each line as question text, option row, or other; extract keywords."""
    for line in lines:
        text = line["text"].strip().lower()
        opt = OPTION_RE.match(text)
        if opt:
            line["kind"] = "option"
            line["option_label"] = opt.group(1).upper()
        elif any(text.startswith(m) for m in QUESTION_MARKERS):
            line["kind"] = "question"
            line["option_label"] = None
        else:
            line["kind"] = "other"
            line["option_label"] = None

        # Significant keywords for matching against the spoken transcript.
        tokens = re.findall(r"[a-z]+(?:'[a-z]+)?", text)
        line["keywords"] = [t for t in tokens if t not in STOPWORDS and len(t) >= 3]

    return {
        "question_lines": [l for l in lines if l["kind"] == "question"],
        "option_lines": [l for l in lines if l["kind"] == "option"],
        "other_lines": [l for l in lines if l["kind"] == "other"],
    }


def analyze_layout(image_path: Path) -> dict[str, Any]:
    """Extract text lines and diagram region from the background image."""
    img = cv2.imread(str(image_path))
    if img is None:
        raise ValueError(f"could not read image: {image_path}")
    h, w = img.shape[:2]

    data = pytesseract.image_to_data(str(image_path), output_type=pytesseract.Output.DICT)
    lines = _line_grouping(data)
    classified = _classify(lines)
    diagram = _diagram_region(img, lines)

    return {
        "image_size": [w, h],
        "diagram": diagram,
        **classified,
    }


def write_layout(layout: dict[str, Any], path: Path) -> None:
    path.write_text(json.dumps(layout, indent=2), encoding="utf-8")
