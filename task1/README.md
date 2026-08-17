# Task 01 — Automated Annotation System (Synthetic Demo)

Pipeline that takes a **static background image** (question + diagram space) and
an **audio narration** (teacher explaining the solution) and produces an **MP4**
in which annotations (highlights, underlines, option boxes, formula labels)
appear over the background image, timed to the narration.

> **IMPORTANT:** This repo currently ships with a **synthetic demo input pair**
> (`demo_input/`). It is *not* the official PW assignment input. It exists so the
> pipeline can be developed, tested and demonstrated end-to-end now, and it is
> labelled as such on the image itself. Replacing it with the real inputs is a
> drop-in substitution (see below) — no pipeline code changes.

---

## 1. What the pipeline does

```
background.png + narration.wav
        │
        ▼
[1] transcribe ──► output/transcript.json   (Whisper, word-level timestamps)
        │
[2] layout ──────► output/layout.json       (Tesseract text lines, options, diagram space)
        │
[3] plan ────────► output/timeline.json     (deterministic annotation events + reasons)
        │
[4] render ──────► output/annotated_video.mp4  (OpenCV/PIL frames + ffmpeg mux)
```

All intermediate artefacts are written to `output/` so every annotation decision
is auditable: `transcript.json` (what was said, and when), `layout.json` (where
things are on the page), `timeline.json` (what was drawn, when, and why).

## 2. Annotations produced

| Action | Trigger rule | What it looks like |
|---|---|---|
| `highlight` | Spoken words fuzzy-match ≥2 keywords of a question-text line (`H1`) | translucent yellow band behind that line |
| `underline` | A keyword appearing in the question text is spoken for the first time (`U1`) | blue line under that word |
| `box` | Teacher says "option X" (`B1`); emphasised if "correct answer" is also said | red/blue rectangle around the option row |
| `label` | Teacher says a formula pattern "<term> equals <expr>" (`L1`) | term badge in the diagram space + arrow to its centre |

The rule table is defined in `src/plan.py` (`RULES`) and each event carries a
`rule` id and a human-readable `reason`. **No LLM is involved** — the planning
stage is fully deterministic and explainable.

## 3. Setup

```bash
# System deps (Debian/Ubuntu)
sudo apt-get install -y ffmpeg tesseract-ocr

# Python deps
pip install -r requirements.txt

# Generate the synthetic demo input (background.png + narration.wav + manifest)
python scripts/make_demo_input.py
```

Notes:
- `scripts/make_demo_input.py` downloads a small piper TTS voice model
  (~63 MB) into `demo_input/voices/` on first run.
- The default ASR model is Whisper `tiny` (smallest, works within the limited
  RAM of the dev environment). Pass `--model base` for better accuracy if memory
  permits.

## 4. Running the pipeline

```bash
python run.py --image demo_input/background.png --audio demo_input/narration.wav \
    --model tiny --output-dir output
```

Outputs written to `output/`:
- `transcript.json` — ASR segments + per-word timestamps
- `layout.json` — detected text lines, option rows, diagram space
- `timeline.json` — annotation events with start/end times, regions and reasons
- `annotated_video.mp4` — the final annotated video

Stage caching: use `--skip-transcribe --skip-layout --skip-plan` to re-render
from existing JSON artefacts.

## 5. Architecture / design decisions

- **Modular stages, stable intermediate formats.** Each stage reads/writes JSON,
  so any stage can be rerun independently or swapped. This is what makes the
  real-input substitution a drop-in change.
- **Synchronisation = word-level ASR timestamps.** Whisper (via faster-whisper)
  produces a start/end time per spoken word. An annotation event begins at the
  first word that triggers its rule, and persists for the rest of the video
  (like a teacher who doesn't erase).
- **Deterministic planning.** Rules match transcript words against detected
  layout keywords with fuzzy string matching. No random sampling, no model
  calls — identical inputs always produce identical timelines.
- **Diagram-space discovery.** Tesseract word boxes are projected onto a grid;
  the largest text-free cell cluster is treated as the diagram area (fallback:
  bottom-right quadrant). Labels are placed there and an arrow points to its
  centre.
- **Rendering.** Each frame is drawn from the base image + all active events;
  raw BGR frames are piped straight into ffmpeg (`libx264` + `aac`), so no huge
  intermediate files are written. `-shortest` trims to the audio length.

## 6. Limitations (honest)

- **Keyword/step-driven annotations only.** The system draws highlights,
  underlines, boxes and labels derived from *what is on the page and what is
  said*. It does **not** guess what a real teacher would hand-draw on an
  arbitrary unseen diagram — that is research-grade and out of scope.
- **ASR accuracy bounds sync quality.** Whisper `tiny` may mis-hear accents,
  names, or numbers; sync degrades if transcription drifts. Segment-level
  timing is the fallback granularity.
- **OCR-dependent layout.** Text must be legible for Tesseract; diagrams that
  contain lots of text will reduce the detected "empty" diagram space.
- **Formula labels** only fire for the simple spoken pattern
  `<term> equals <expr>` (with `times`/`multiplied by`). Complex spoken math
  is not covered.
- **Resource limits.** The dev environment has ~2 CPU cores and tight RAM;
  Whisper `tiny` is used by default. Long narrations are slow; a demo narration
  of ~45 s is the tested size.

## 7. Substituting the real PW inputs

The pipeline reads any image and any audio file. To use the real inputs:

```bash
python run.py --image /path/to/real_background.png \
    --audio /path/to/real_narration.mp3 \
    --model tiny --output-dir output_real
```

No pipeline code changes are needed. What *may* need tuning for a real input:

- The **diagram-space heuristic** (blank-region grid) if the real layout differs
  (e.g. diagram crowded with text).
- The **option-row classifier** (`OPTION_RE` in `src/layout.py`) if option labels
  use a different format than `A) ...`.
- The **Whisper model size** (`--model base/small`) if the real narration has
  accents or background noise.

The synthetic manifest (`demo_input/manifest.json`) records exactly which files
were generated, so nothing here can be mistaken for official input.

## 8. Testing

```bash
python -m pytest tests -q
```

Covers: plan rules (highlight/box/label/underline, stopword filtering, ordering,
persistence, dedupe), layout detection on the demo image, and transcription of
the demo audio. The heavy tests (`layout`, `transcribe`) skip automatically if
the demo input files are absent.

## 9. File layout

```
task1/
├── run.py                     # CLI entry point
├── requirements.txt
├── scripts/
│   └── make_demo_input.py     # generates synthetic demo background + narration
├── demo_input/                # SYNTHETIC demo input (clearly labelled)
│   ├── background.png
│   ├── narration.txt
│   ├── narration.wav
│   └── manifest.json
├── src/
│   ├── transcribe.py          # Whisper ASR + word timestamps
│   ├── layout.py              # Tesseract text/option/diagram detection
│   ├── plan.py                # deterministic annotation rules
│   └── render.py              # frame rendering + ffmpeg mux
├── output/                    # generated artefacts (gitignored)
└── tests/test_pipeline.py
```
