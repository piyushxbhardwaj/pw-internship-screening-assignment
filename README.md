# Task 03 — Fix a Broken Workflow

Reconcile a question-bank batch (**PDF** + **ZIP** of screenshots + **Excel**
metadata) and produce canonically named `Q1.png, S1.png, Q2.png, S2.png, ...`
files **from the existing ZIP** — with no one taking fresh screenshots.

## What is actually broken

The symptom reported in the assignment is "employees manually re-screenshot the
PDF and rename files." That is not the real problem — it is the workaround.
The actual breakage has three layers:

1. **The ZIP's filenames destroy image identity.** The screenshots exist but
   are named like `QUES_ENG_6bu4xk0nseoellblow8ysi9ru.png`. The prefix encodes
   *type* (`QUES_`/`SOLU_`) and *language* (`ENG`), but **not display order** —
   so the files cannot be ordered or paired without external information.
2. **The Excel metadata already contains the full mapping, and it is ignored.**
   The `Display Order`, `Question Image`, and `Sol Image` columns tie every
   screenshot to its question. The manual process throws this away and rebuilds
   it by hand.
3. **Re-screenshotting degrades data.** Hand-taken crops differ in resolution,
   margins, and pixel content from the official images, so the "fix" introduces
   drift instead of restoring quality.

**The correct fix is a deterministic reconciliation layer** — read the
metadata, match every image, validate the result, and copy to canonical names.
No ML is needed for the primary path; that is a feature, not a shortcut.

## Can the existing ZIP be used directly?

**Yes — verified on the real batch** (`Test_1785232337613.*`):

| Check | Result |
|---|---|
| Excel rows | 75 (Display Orders 1–75, contiguous) |
| ZIP images | 150 (75 questions + 75 solutions) |
| Referenced images missing from ZIP | 0 |
| ZIP images not referenced by Excel | 0 |
| Duplicate references | 0 |
| Output produced / byte-verified | 150 / 150 |

The tool always runs an **integrity audit** so this verdict is evidenced, not
assumed.

## How it works

```
input/
  question_paper.pdf     (source of truth for order/text; optional for direct mode)
  images.zip             (randomly named screenshots)
  metadata.xlsx          (question <-> image mapping)
        |
        v
  [1] zip_reader   safe extraction (zip-slip guard, image filter)
  [2] excel_reader schema auto-detection -> (order, question image, sol image) cols
  [3] matcher      direct Excel mapping  OR  content fallback (OCR + PDF text)
  [4] audit        cross-check ZIP vs Excel -> usability verdict
  [5] renamer      copy to output/Q<i>.<ext>, S<i>.<ext> (never mutates originals)
  [6] report       report.csv manifest + console summary
        |
        v
output/
  Q1.png  S1.png  Q2.png  S2.png ...  +  report.csv
```

### Matching strategy (priority order)

1. **Direct (deterministic, exact):** the Excel `Question Image` / `Sol Image`
   columns reference the ZIP filenames. Rename is a pure lookup. This is the
   primary path and the one used for the real batch.
2. **Content fallback (only when the Excel has no image columns):** parse the
   PDF into per-question blocks, OCR every screenshot, fuzzy-match image text to
   question/solution text, and pick the best match per question. Filename
   prefixes like `QUES_`/`SOLU_`, when present, override the Q-vs-S
   classification.

### Honest limits of the fallback (measured, not guessed)

On the real batch the fallback matched **75/75 questions** but only **53/75
solutions**. Root cause: PW's solution content is math-heavy. Math equations do
not survive PDF text extraction (the solution text layer is mostly marker
noise), and generic OCR mangles math notation — so neither side is clean enough
to fuzzy-match reliably. Generic OCR cannot be forced to 100% on math without
specialized (and non-free) math OCR. The tool therefore **reports unmatched
images instead of guessing**, which is the correct production behavior.

## Project layout

```
task3/
├── input/                  real PW batch (Test_1785232337613.*) - not required to run tests
├── output/                 generated Q1.png..S75.png + report.csv  (from real batch)
├── src/
│   ├── config.py           column auto-detection + tunables
│   ├── excel_reader.py     Excel parsing -> Record(order, question_image, solution_image)
│   ├── zip_reader.py       safe extraction, zip-slip protection
│   ├── audit.py            ZIP vs Excel integrity cross-check + verdict
│   ├── fallback.py         PDF block extraction + OCR + fuzzy matching
│   ├── renamer.py          build & execute the rename/copy plan
│   └── report.py           report.csv + console summary
├── scripts/make_fixture.py generates synthetic test batches
├── fixtures/synthetic/     generated synthetic fixtures (3 variants)
├── tests/test_workflow.py  13 pytest tests
├── rename_workflow.py      CLI entry point
└── requirements.txt
```

## Setup

```bash
python3 -m venv .venv
source .venv/bin/activate
pip install -r requirements.txt
```

The content-fallback path also needs the Tesseract OCR binary:
```bash
sudo apt-get install -y tesseract-ocr
```

## Usage

```bash
# Run on the real batch (produces output/Q1.png ... S75.png)
python rename_workflow.py --input-dir input --output-dir output

# Preview the plan without copying anything
python rename_workflow.py --input-dir input --output-dir output --dry-run

# Force the content-based fallback (exercises OCR + PDF matching)
python rename_workflow.py --input-dir input --output-dir output_fallback --force-fallback

# Batch whose Excel has NO image filename columns -> fallback auto-triggers
python rename_workflow.py --input-dir fixtures/synthetic/no_mapping --output-dir /tmp/out

# Keep the extracted ZIP workdir for debugging
python rename_workflow.py --input-dir input --output-dir output --keep-temp
```

## Testing

```bash
# Generate synthetic fixtures (also done once by the test run)
python scripts/make_fixture.py

# Run the full test suite (real-batch test auto-skips if input/ is absent)
pytest tests/ -v
```

The suite covers: ZIP zip-slip rejection, non-image skipping, schema detection
(including header variants), direct-mode byte-for-byte round trips, fallback
round trips, audit detection of missing/unreferenced/duplicate images, and edge
fixtures that flag issues instead of silently guessing.

## Design choices

- **`openpyxl` over pandas**: only table reads are needed; one fewer dependency
  and faster to explain.
- **`PyMuPDF`**: fast per-page text extraction; only needed by the fallback.
- **`rapidfuzz`**: fuzzy matching tolerant of OCR noise (`token_set_ratio`
  ignores token order and handles extra tokens).
- **No LLMs / deep learning anywhere**: the primary problem is a deterministic
  data-reconciliation problem. Adding AI here would reduce reliability, add
  cost and latency, and make the failure modes opaque. The fallback uses
  classical OCR + fuzzy matching, which is explainable and auditable.

## Assumptions (all configurable)

1. Excel is `.xlsx`, one row per question, with a display-order column.
2. Output names are `Q<i>.<ext>` / `S<i>.<ext>` using the source extension.
3. One solution image per question (multiple would be reported, not guessed).
4. PDF text is extractable for the fallback (scanned PDFs are rejected loudly).
5. Originals are never modified; the tool copies.
