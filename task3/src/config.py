"""Configuration for the workflow.

Defaults match the schema of the provided real batch
(Test_1785232337613.xlsx). Column detection is keyword-based so that
slightly different header names in future batches still work.
"""

from dataclasses import dataclass, field


def _norm(text: str) -> str:
    """Lowercase and strip non-alphanumeric chars: 'Display Order*' -> 'displayorder'."""
    return "".join(ch for ch in text.lower() if ch.isalnum())


@dataclass
class Config:
    # Keyword groups used to auto-detect columns. Order matters (first match wins).
    order_keywords: list = field(default_factory=lambda: [
        "displayorder", "displayorder*", "qno", "questionno", "questionnumber",
        "srno", "sno", "index", "serialno",
    ])
    question_image_keywords: list = field(default_factory=lambda: [
        "questionimage", "quesimage", "qimage", "questionimagepath",
    ])
    solution_image_keywords: list = field(default_factory=lambda: [
        "solimage", "solutionimage", "simage", "solutionimagepath",
    ])

    # Filename prefix hints (used by the fallback matcher when present).
    question_prefixes: tuple = ("QUES_", "Q_")
    solution_prefixes: tuple = ("SOLU_", "SOL_", "S_")

    # Content-matching fallback settings.
    match_threshold: float = 55.0          # rapidfuzz score (%); below => unmatched
    ocr_scale: float = 2.0                 # upscale factor for OCR accuracy

    # A scanned PDF (no digital text) is a hard failure for the fallback.
    require_pdf_text: bool = True

    # Extension assumed for rows that reference no source file (report only).
    default_ext: str = "png"

    def detect_columns(self, header):
        """Map header strings to column indices.

        Returns a dict with keys 'order', 'qimg', 'simg' whose values are
        column indices or None.
        """
        cols = {k: None for k in ("order", "qimg", "simg")}
        groups = {
            "order": self.order_keywords,
            "qimg": self.question_image_keywords,
            "simg": self.solution_image_keywords,
        }
        for k, keywords in groups.items():
            for idx, raw in enumerate(header):
                if raw is None:
                    continue
                norm = _norm(str(raw))
                for kw in keywords:
                    kw_norm = _norm(kw)
                    if norm == kw_norm or kw_norm in norm:
                        cols[k] = idx
                        break
                if cols[k] is not None:
                    break
        return cols
