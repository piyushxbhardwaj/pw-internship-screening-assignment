"""Content-based fallback matching.

Used only when the Excel metadata does not reference image filenames.
Pipeline:
  1. Parse the PDF into per-question text blocks (question text and solution
     text for each Q number).
  2. OCR every ZIP image.
  3. Fuzzy-match each image's OCR text to the closest question/solution block.
  4. Assemble the best question and solution image per question number.

Filename prefixes such as QUES_/SOLU_ (when present) are used as a type hint
that overrides the OCR-based Q-vs-S classification.
"""

import re

from .config import Config

try:
    import pymupdf as fitz
except ImportError:  # pragma: no cover
    import fitz

import pytesseract
from PIL import Image
from rapidfuzz import fuzz

Q_MARKER = re.compile(r"^Q(\d{1,3})\s*$")


def normalize(text: str) -> str:
    return " ".join(text.split())


def extract_blocks(pdf_path: str) -> dict:
    """Return {q_number: {'question': str, 'solution': str}}.

    Assumes the paper structure is: Q<n> <question text> ... Q<n> <solution
    text> ... (each question number appears twice: once for the question,
    once for its solution), which matches the real PW batch.
    """
    doc = fitz.open(pdf_path)
    full = "\n".join(page.get_text() for page in doc)
    lines = full.splitlines()

    blocks = {}
    current_num = None
    current_kind = None
    seen = {}
    for raw in lines:
        m = Q_MARKER.match(raw.strip())
        if m:
            num = int(m.group(1))
            seen[num] = seen.get(num, 0) + 1
            current_num = num
            current_kind = "question" if seen[num] == 1 else "solution"
            blocks.setdefault(num, {"question": [], "solution": []})
            continue
        if current_num is not None and raw.strip():
            blocks[current_num][current_kind].append(raw)

    return {
        n: {"question": normalize(" ".join(d["question"])),
            "solution": normalize(" ".join(d["solution"]))}
        for n, d in blocks.items()
    }


def ocr_image(path: str, cfg: Config) -> str:
    img = Image.open(path)
    if img.mode not in ("L", "RGB"):
        img = img.convert("RGB")
    if cfg.ocr_scale != 1.0:
        img = img.resize(
            (int(img.width * cfg.ocr_scale), int(img.height * cfg.ocr_scale)),
            Image.LANCZOS,
        )
    return normalize(pytesseract.image_to_string(img))


def _kind_from_filename(name: str, cfg: Config) -> str | None:
    upper = name.upper()
    if any(upper.startswith(p.upper()) for p in cfg.question_prefixes):
        return "question"
    if any(upper.startswith(p.upper()) for p in cfg.solution_prefixes):
        return "solution"
    return None


def match_by_content(records, images: dict, pdf_path: str, cfg: Config):
    """Match ZIP images to questions/solutions using PDF text + OCR.

    Args:
        records: list[Record] (only .order is used here).
        images:  dict of {zip filename: extracted local path}.
        pdf_path: path to the question paper PDF.

    Returns:
        (result, per_image) where
          result[order] = {'q': name|None, 's': name|None, 'q_score': float, 's_score': float}
          per_image[name] = {'order': int|None, 'kind': str|None, 'score': float,
                             'note': str}
    """
    blocks = extract_blocks(pdf_path)
    numbers = sorted(blocks.keys())
    orders = sorted(r.order for r in records)

    if numbers != orders:
        raise ValueError(
            f"PDF question numbers {numbers} do not align with Excel display "
            f"orders {orders}; cannot run the content fallback on this batch."
        )
    if any(not b["question"] for b in blocks.values()):
        raise ValueError("PDF contains no extractable question text (scanned PDF?).")

    # 1) OCR every image.
    ocr_texts = {}
    for name, path in images.items():
        try:
            ocr_texts[name] = ocr_image(path, cfg)
        except Exception:
            ocr_texts[name] = ""

    # 2) Classify every image against all blocks.
    candidates = {}  # order -> list of (name, kind, score)
    per_image = {}
    for name, text in ocr_texts.items():
        best = None  # (score, kind, number)
        if text:
            for num in numbers:
                q_score = fuzz.token_set_ratio(text, blocks[num]["question"])
                s_score = fuzz.token_set_ratio(text, blocks[num]["solution"])
                for kind, score in (("question", q_score), ("solution", s_score)):
                    if best is None or score > best[0]:
                        best = (score, kind, num)

        hint = _kind_from_filename(name, cfg)
        if best and hint:
            best = (best[0], hint, best[2])

        if best and best[0] >= cfg.match_threshold:
            candidates.setdefault(best[2], []).append((name, best[1], best[0]))
            per_image[name] = {"order": best[2], "kind": best[1], "score": best[0], "note": "matched"}
        else:
            per_image[name] = {
                "order": None,
                "kind": None,
                "score": best[0] if best else 0.0,
                "note": "below threshold" if best else "no OCR text",
            }

    # 3) Assemble best Q and best S per order.
    result = {}
    for order in orders:
        cands = candidates.get(order, [])
        qs = [c for c in cands if c[1] == "question"]
        ss = [c for c in cands if c[1] == "solution"]
        q = max(qs, key=lambda c: c[2]) if qs else None
        s = max(ss, key=lambda c: c[2]) if ss else None

        selected = {q[0] if q else None, s[0] if s else None}
        for name, kind, score in cands:
            if name not in selected:
                per_image[name]["note"] = "matched but not selected (over-assigned)"

        result[order] = {
            "q": q[0] if q else None,
            "s": s[0] if s else None,
            "q_score": round(q[2], 1) if q else 0.0,
            "s_score": round(s[2], 1) if s else 0.0,
        }
    return result, per_image
