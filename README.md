# PW Internship Screening Assignment

Complete submission for the **Physics Wallah (PW) Internship Screening
Assignment**. This repository contains the solutions to three tasks:

| Task | Directory | Topic |
|---|---|---|
| 01 | [`task1/`](task1/) | Automated annotation system (background image + narration → annotated video) |
| 02 | [`task2/`](task2/) | "Brief an AI to write in my voice" — Computer Networks voice brief |
| 03 | [`task3/`](task3/) | Fix a broken image-renaming workflow |

---

## Task 01 — Automated Annotation System

A pipeline that takes a **static background image** (a question with a diagram
space) and an **audio narration** (a teacher explaining the solution) and
produces an **MP4** where annotations appear over the background image, timed
to the narration.

### Pipeline

```
background.png + narration.wav
        │
        ▼
[1] transcribe ──► output/transcript.json   (Whisper, word-level timestamps)
        │
[2] layout ──────► output/layout.json       (text lines, options, diagram space)
        │
[3] plan ────────► output/timeline.json     (deterministic annotation events + reasons)
        │
[4] render ──────► output/annotated_video.mp4  (frames + ffmpeg mux)
```

- **Transcribe**: faster-whisper (Whisper `tiny` by default) produces a
  start/end time per spoken word.
- **Layout**: Tesseract locates question-text lines, option rows, and the
  diagram space (largest text-free region).
- **Plan**: a deterministic rule table (no LLM) turns the transcript + layout
  into annotation events — highlights, underlines, option boxes, and formula
  labels — each carrying an auditable `rule` and `reason`.
- **Render**: per-frame drawing, piped into ffmpeg (`libx264` + `aac`).

### How to run

```bash
# System deps
sudo apt-get install -y ffmpeg tesseract-ocr

# Python deps
pip install -r task1/requirements.txt

# Generate the synthetic demo input
python task1/scripts/make_demo_input.py

# Run the full pipeline
python task1/run.py --image task1/demo_input/background.png \
    --audio task1/demo_input/narration.wav \
    --model tiny --output-dir task1/output
```

### Validation note

Validation was performed end-to-end using a **clearly labelled synthetic demo
input pair** (`task1/demo_input/`), because **the real PW Task 01 inputs
(background image + narration audio) were not available**. The demo is labelled
as synthetic both in `task1/demo_input/manifest.json` and on the image itself.
The pipeline reads any image/audio, so real inputs can be substituted directly:

```bash
python task1/run.py --image /path/to/real_background.png \
    --audio /path/to/real_narration.mp3 --model tiny --output-dir task1/output_real
```

Full details: [`task1/README.md`](task1/README.md)

## Task 02 — "Brief an AI to Write in My Voice"

[`task2/brief.md`](task2/brief.md) contains the Computer Networks voice brief —
an explicit style guide for an AI to answer CN questions the way the author
would (strengths, weaknesses, structure, terminology habits, and exam-pressure
behaviour).

## Task 03 — Fix a Broken Workflow

A question-bank batch consists of a **PDF**, a **ZIP of screenshots**, and an
**Excel metadata sheet**. The broken manual process re-screenshots and renames
files by hand. The fix here is a **deterministic reconciliation layer** that
reads the Excel metadata to map the existing question/solution images to
canonical names (`Q1.png`, `S1.png`, `Q2.png`, `S2.png`, …), with an OCR/PDF
fuzzy-match fallback only when the Excel metadata lacks image references.

Verified on the real batch: 75 Excel rows, 150 images in the ZIP, zero
missing/unreferenced/duplicate references, 150/150 outputs byte-verified
(`md5` identical to source). See [`task3/README.md`](task3/README.md) for setup
and usage.

---

## Setup

- Python 3.11+
- Task 01: `ffmpeg`, `tesseract-ocr`, `pip install -r task1/requirements.txt`
- Task 03: `pip install -r task3/requirements.txt` (see its README for the
  optional fallback dependencies)

## Limitations / Notes

- **Task 01**: tested with a synthetic demo only — real PW inputs were not
  available. Annotation set is keyword/step-driven (highlight, underline, box,
  label); it does not guess what a human teacher would hand-draw on an unseen
  diagram. Sync quality is bounded by ASR accuracy (Whisper `tiny` used to fit
  constrained RAM).
- **Task 03**: the OCR/PDF fallback handles questions well but not solution
  images (math doesn't survive PDF text extraction); unmatched images are
  refused rather than guessed.
- Generated artifacts (`task1/output*/`, `task3/output*/`) are gitignored and
  not committed.
