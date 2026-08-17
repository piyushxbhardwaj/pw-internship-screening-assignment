#!/usr/bin/env python3
"""Generate synthetic fixture batches for testing the Task 03 pipeline.

Why fixtures? The real batch (Test_1785232337613.*) must NOT be edited or
committed, and tests need to run anywhere. These fixtures simulate realistic
input files (PDF + ZIP + Excel) with controlled, known answers so tests are
deterministic. They are clearly labeled as synthetic test data.

Three fixture sets are produced under fixtures/synthetic/:
  with_mapping/  - Excel references image filenames (direct path)
  no_mapping/    - Excel has NO image columns (exercises the content fallback)
  edge_cases/    - missing reference + unreferenced image + duplicate (audit)

Usage:
    python scripts/make_fixture.py [--out fixtures/synthetic]
"""

import argparse
import os
import random
import shutil
import uuid

import fitz
import openpyxl
from PIL import Image, ImageDraw, ImageFont

FONT = "/usr/share/fonts/truetype/dejavu/DejaVuSans.ttf"
FONT_SIZE = 26

QUESTIONS = {
    1: "What is the capital of India and which river flows through it?",
    2: "Explain Newton's second law of motion in your own words.",
    3: "A train covers 300 km in 5 hours. Calculate its average speed.",
    4: "Describe the difference between a solar eclipse and a lunar eclipse.",
    5: "What is the chemical formula of water and why is it important?",
}
SOLUTIONS = {
    1: "New Delhi is the capital of India. The Yamuna river flows through it.",
    2: "The acceleration of an object depends on the net force acting on it and its mass.",
    3: "Average speed equals total distance divided by total time, so 60 km per hour.",
    4: "A solar eclipse happens when the moon blocks the sun from the earth.",
    5: "Water has the formula H2O and is essential for all known forms of life.",
}


def render_png(text: str, path: str) -> None:
    """Render text to a white PNG so tesseract can OCR it reliably."""
    font = ImageFont.truetype(FONT, FONT_SIZE)
    lines = []
    for para in text.splitlines():
        line, width, _ = "", 0, None
        for word in para.split():
            w = font.getlength(word)
            if line and width + w > 780:
                lines.append(line)
                line, width = "", 0
            line += (" " if line else "") + word
            width += w + font.getlength(" ")
        lines.append(line)
    width = min(1000, max(200, int(max(font.getlength(l) for l in lines) + 60)))
    height = 30 + FONT_SIZE * len(lines) + 30
    img = Image.new("RGB", (width, height), "white")
    draw = ImageDraw.Draw(img)
    y = 20
    for ln in lines:
        draw.text((20, y), ln, fill="black", font=font)
        y += FONT_SIZE + 8
    img.save(path)


def build_pdf(questions: dict, solutions: dict, path: str) -> None:
    doc = fitz.open()
    page = doc.new_page()
    y = 72
    for num in questions:
        for kind, text in (("q", questions[num]), ("s", solutions[num])):
            page.insert_text((72, y), f"Q{num}", fontsize=12)
            y += 18
            for ln in _wrap(text, 80):
                page.insert_text((72, y), ln, fontsize=11)
                y += 15
            y += 6
        if y > 700:
            page = doc.new_page()
            y = 72
    doc.save(path)
    doc.close()


def _wrap(text: str, width: int) -> list:
    words, lines, line = text.split(), [], ""
    for w in words:
        if len(line) + len(w) + 1 > width:
            lines.append(line)
            line = w
        else:
            line = (line + " " + w).strip()
    if line:
        lines.append(line)
    return lines


def _random_name() -> str:
    return f"img_{uuid.uuid4().hex[:12]}.png"


def _zip_images(images: dict, zip_path: str) -> None:
    import zipfile
    with zipfile.ZipFile(zip_path, "w") as zf:
        for name, path in images.items():
            zf.write(path, name)


def make_set(out_dir: str, with_mapping: bool, edge_case: bool = False) -> None:
    """Generate one fixture batch directory."""
    os.makedirs(out_dir, exist_ok=True)
    img_dir = os.path.join(out_dir, "_raw")
    os.makedirs(img_dir, exist_ok=True)

    names = {}
    for num in QUESTIONS:
        q_path = os.path.join(img_dir, f"q{num}.png")
        s_path = os.path.join(img_dir, f"s{num}.png")
        render_png(QUESTIONS[num], q_path)
        render_png(SOLUTIONS[num], s_path)
        names[num] = {"q": _random_name(), "s": _random_name()}

    # Randomize: copy rendered PNGs under random names (no QUES_/SOLU_ hints).
    zip_images = {}
    for num, pair in names.items():
        zip_images[pair["q"]] = os.path.join(img_dir, f"q{num}.png")
        zip_images[pair["s"]] = os.path.join(img_dir, f"s{num}.png")

    if edge_case:
        # 1) A referenced image that is NOT in the ZIP.
        names[3]["q"] = "img_missing_from_zip.png"
        # 2) An extra image in the ZIP that the Excel never references.
        orphan = f"img_{uuid.uuid4().hex[:12]}.png"
        zip_images[orphan] = os.path.join(img_dir, "q1.png")

    _zip_images(zip_images, os.path.join(out_dir, "images.zip"))
    build_pdf(QUESTIONS, SOLUTIONS, os.path.join(out_dir, "question_paper.pdf"))

    wb = openpyxl.Workbook()
    ws = wb.active
    ws.title = "Sheet 1"
    if with_mapping:
        ws.append(["Display Order*", "Question Text", "Question Image", "Sol Image"])
        for num in QUESTIONS:
            ws.append([num, QUESTIONS[num], names[num]["q"], names[num]["s"]])
    else:
        ws.append(["Display Order*", "Question Text"])
        for num in QUESTIONS:
            ws.append([num, QUESTIONS[num]])
    wb.save(os.path.join(out_dir, "metadata.xlsx"))

    shutil.rmtree(img_dir, ignore_errors=True)
    print(f"  wrote {out_dir}")


def main() -> None:
    ap = argparse.ArgumentParser(description="Generate synthetic fixtures")
    ap.add_argument("--out", default=os.path.join(os.path.dirname(__file__), "..", "fixtures", "synthetic"))
    args = ap.parse_args()
    base = args.out
    if os.path.isdir(base):
        shutil.rmtree(base, ignore_errors=True)
    print("Generating synthetic fixture batches:")
    make_set(os.path.join(base, "with_mapping"), with_mapping=True)
    make_set(os.path.join(base, "no_mapping"), with_mapping=False)
    make_set(os.path.join(base, "edge_cases"), with_mapping=True, edge_case=True)


if __name__ == "__main__":
    random.seed(42)
    main()
