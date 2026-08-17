"""Build and execute the rename/copy plan.

Originals in the extracted ZIP workdir are never modified; we copy them into
the output directory under canonical Q<i>.<ext> / S<i>.<ext> names.
"""

import os
import shutil
from dataclasses import dataclass

from .config import Config


@dataclass
class FileTask:
    order: int
    kind: str                # 'question' | 'solution'
    src_name: str            # original name inside the ZIP
    src_path: str            # extracted local path (empty if unavailable)
    dst_name: str            # canonical output name
    status: str = "pending"
    note: str = ""

    @property
    def prefix(self) -> str:
        return "Q" if self.kind == "question" else "S"


def dst_name(order: int, prefix: str, ext: str) -> str:
    return f"{prefix}{order}.{ext.lstrip('.')}"


def build_tasks(records, extracted: dict, cfg: Config, mode: str,
                fallback_result: dict | None = None) -> list:
    """Build the FileTask list from either the direct (Excel) mapping or the
    content-fallback result.

    mode: 'direct' or 'fallback'.
    """
    tasks = []
    used_dst = {}

    def add(rec_order, kind, src_name, src_path, status, note):
        prefix = "Q" if kind == "question" else "S"
        ext = os.path.splitext(src_name)[1].lstrip(".") if src_name else cfg.default_ext
        name = dst_name(rec_order, prefix, ext)
        if name in used_dst:
            tasks.append(FileTask(rec_order, kind, src_name, src_path, name, "conflict",
                                  f"output name collides with {used_dst[name]}"))
            return
        used_dst[name] = src_name or "<unknown>"
        tasks.append(FileTask(rec_order, kind, src_name, src_path, name, status, note))

    if mode == "direct":
        for rec in records:
            for kind, attr in (("question", "question_image"), ("solution", "solution_image")):
                src_name = getattr(rec, attr)
                if not src_name:
                    add(rec.order, kind, "", "", "missing_reference", "no filename in Excel")
                    continue
                src_path = extracted.get(src_name)
                if src_path is None:
                    add(rec.order, kind, src_name, "", "missing_in_zip",
                        "referenced by Excel but absent from ZIP")
                    continue
                add(rec.order, kind, src_name, src_path, "ok", "")

    elif mode == "fallback":
        for rec in records:
            m = fallback_result.get(rec.order, {})
            for kind, key in (("question", "q"), ("solution", "s")):
                src_name = m.get(key)
                score = m.get(f"{key}_score", 0.0)
                if not src_name:
                    add(rec.order, kind, "", "", "unmatched",
                        f"no image matched (best score {score})")
                    continue
                src_path = extracted.get(src_name)
                add(rec.order, kind, src_name, src_path, "ok",
                    f"content match score {score}")
    else:  # pragma: no cover
        raise ValueError(f"unknown mode {mode}")

    return tasks


def execute(tasks: list, output_dir: str, dry_run: bool) -> None:
    os.makedirs(output_dir, exist_ok=True)
    for t in tasks:
        if t.status != "ok":
            continue
        if dry_run:
            t.status = "dry_run"
            continue
        if not t.src_path or not os.path.exists(t.src_path):
            t.status = "missing_in_zip"
            continue
        dst_path = os.path.join(output_dir, t.dst_name)
        shutil.copy2(t.src_path, dst_path)
        t.status = "copied"
