"""Excel metadata reading and column auto-detection."""

from dataclasses import dataclass
from typing import Optional

import openpyxl

from .config import Config


@dataclass
class Record:
    """One question row from the Excel metadata."""

    order: int                          # canonical question index (Display Order)
    question_image: Optional[str] = None   # ZIP filename of the question screenshot
    solution_image: Optional[str] = None   # ZIP filename of the solution screenshot
    extra: dict = None

    def __post_init__(self):
        if self.extra is None:
            self.extra = {}


def read_records(xlsx_path: str, cfg: Config) -> tuple:
    """Read the metadata workbook.

    Returns (records, schema) where schema is the detected column map from
    cfg.detect_columns(). Column detection is performed on the header row.
    """
    wb = openpyxl.load_workbook(xlsx_path, data_only=True, read_only=True)
    ws = wb.active
    rows = ws.iter_rows(values_only=True)
    try:
        header = list(next(rows))
    except StopIteration:
        raise ValueError(f"workbook {xlsx_path} is empty")

    schema = cfg.detect_columns(header)
    if schema["order"] is None:
        raise ValueError(
            f"could not auto-detect a question-order column in {xlsx_path}; "
            f"header was {header}"
        )

    records = []
    for row in rows:
        order_raw = row[schema["order"]]
        if order_raw is None:
            continue  # trailing empty row
        try:
            order = int(order_raw)
        except (TypeError, ValueError):
            raise ValueError(f"non-integer display order {order_raw!r} in row {row}")

        qimg = row[schema["qimg"]] if schema["qimg"] is not None else None
        simg = row[schema["simg"]] if schema["simg"] is not None else None
        records.append(Record(
            order=order,
            question_image=str(qimg) if qimg else None,
            solution_image=str(simg) if simg else None,
            extra=dict(zip(header, row)),
        ))
    return records, schema
