"""Integrity audit: is the existing ZIP usable directly?

Cross-checks the Excel metadata against the ZIP contents so we can answer the
assignment's core question ("can the existing ZIP files be used directly?")
with evidence rather than guesswork.
"""

from dataclasses import dataclass, field
from typing import Optional

from .excel_reader import Record


@dataclass
class AuditResult:
    has_image_refs: bool = True         # Excel has Question Image / Sol Image columns
    total_zip_images: int = 0
    total_rows: int = 0
    rows_missing_q_ref: int = 0
    rows_missing_s_ref: int = 0
    q_refs_missing_in_zip: list = field(default_factory=list)
    s_refs_missing_in_zip: list = field(default_factory=list)
    unreferenced_in_zip: list = field(default_factory=list)
    duplicate_refs: list = field(default_factory=list)
    orders_contiguous: bool = True
    order_gaps: list = field(default_factory=list)

    @property
    def coverage(self) -> Optional[float]:
        """Fraction of Excel rows that have both Q and S images available
        (only meaningful when the Excel references image filenames)."""
        if not self.has_image_refs or self.total_rows == 0:
            return None
        complete = (
            self.total_rows
            - self.rows_missing_q_ref
            - self.rows_missing_s_ref
            - len(set(self.q_refs_missing_in_zip))
            - len(set(self.s_refs_missing_in_zip))
        )
        return complete / self.total_rows

    def verdict(self) -> str:
        if not self.has_image_refs:
            return "N/A: Excel has no image columns; usability is decided by the content-fallback matches."
        if (
            self.coverage == 1.0
            and not self.unreferenced_in_zip
            and not self.duplicate_refs
            and self.orders_contiguous
        ):
            return "USABLE: the existing ZIP can be used directly with no manual screenshots."
        if self.coverage == 1.0:
            return "USABLE (with review): mapping is complete but the batch has non-critical issues to check."
        return "PARTIALLY USABLE: some images are missing or unreferenced; review the report before renaming."


def run_audit(records: list, zip_image_names: list, has_image_refs: bool = True) -> AuditResult:
    r = AuditResult(has_image_refs=has_image_refs)
    r.total_rows = len(records)
    zip_set = set(zip_image_names)
    r.total_zip_images = len(zip_set)

    if not has_image_refs:
        # No filename linkage in metadata -> reference-based checks do not apply;
        # matching is content-based and is audited via the task statuses instead.
        orders = [rec.order for rec in records]
        if orders:
            expected = list(range(min(orders), max(orders) + 1))
            r.orders_contiguous = orders == expected
            r.order_gaps = sorted(set(expected) - set(orders))
        return r

    q_refs, s_refs = [], []
    for rec in records:
        if not rec.question_image:
            r.rows_missing_q_ref += 1
        else:
            q_refs.append(rec.question_image)
            if rec.question_image not in zip_set:
                r.q_refs_missing_in_zip.append((rec.order, rec.question_image))
        if not rec.solution_image:
            r.rows_missing_s_ref += 1
        else:
            s_refs.append(rec.solution_image)
            if rec.solution_image not in zip_set:
                r.s_refs_missing_in_zip.append((rec.order, rec.solution_image))

    from collections import Counter
    dup = {k: v for k, v in Counter(q_refs + s_refs).items() if v > 1}
    r.duplicate_refs = sorted(dup.items())

    referenced = set(q_refs) | set(s_refs)
    r.unreferenced_in_zip = sorted(zip_set - referenced)

    orders = [rec.order for rec in records]
    r.total_zip_images = len(zip_set)
    if orders:
        expected = list(range(min(orders), max(orders) + 1))
        r.orders_contiguous = orders == expected
        r.order_gaps = sorted(set(expected) - set(orders))
    return r
