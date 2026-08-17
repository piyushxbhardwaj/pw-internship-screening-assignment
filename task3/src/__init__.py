"""Task 03 - Fix a Broken Workflow.

Reconcile a question-bank batch (PDF + ZIP of screenshots + Excel metadata)
and produce canonically named Q<i>.<ext> / S<i>.<ext> files from the existing
ZIP - no manual re-screenshotting.

Primary strategy (deterministic):
    The Excel metadata references each question and solution image by its ZIP
    filename. We read that mapping and copy/rename the existing images.

Fallback strategy (content-based, only when the Excel has no image columns):
    Extract per-question text blocks from the PDF, OCR every ZIP image, and
    fuzzy-match image text to question/solution blocks.
"""

__version__ = "1.0.0"
