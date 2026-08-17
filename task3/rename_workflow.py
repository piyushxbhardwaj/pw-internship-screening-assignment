#!/usr/bin/env python3
"""Task 03 - Fix a Broken Workflow: reconcile ZIP + Excel (+ PDF) and produce
canonically named Q<i>.<ext> / S<i>.<ext> files from the existing ZIP.

Usage:
    python rename_workflow.py --input-dir input --output-dir output
    python rename_workflow.py --input-dir input --output-dir output --dry-run
    python rename_workflow.py --input-dir input --output-dir output --force-fallback
    python rename_workflow.py --input-dir input --output-dir output --keep-temp
"""

import argparse
import os
import shutil
import sys
import tempfile

sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))

from src import audit as audit_mod
from src import report as report_mod
from src import renamer
from src.config import Config
from src.excel_reader import read_records
from src.fallback import match_by_content
from src.zip_reader import extract_images


def find_input_file(input_dir: str, kinds: tuple, required: bool = False):
    matches = [f for f in os.listdir(input_dir) if f.lower().endswith(kinds)]
    if not matches:
        if required:
            raise FileNotFoundError(
                f"no file matching {kinds} found in {input_dir}"
            )
        return None
    return os.path.join(input_dir, sorted(matches)[0])


def run(input_dir: str, output_dir: str, zip_path: str = None, excel_path: str = None,
        pdf_path: str = None, force_fallback: bool = False, dry_run: bool = False,
        keep_temp: bool = False) -> int:
    """Core pipeline. Returns a process exit code (0 = success)."""
    if not os.path.isdir(input_dir):
        print(f"error: input dir {input_dir!r} does not exist", file=sys.stderr)
        return 2

    zip_path = zip_path or find_input_file(input_dir, (".zip",), required=True)
    excel_path = excel_path or find_input_file(input_dir, (".xlsx", ".xls"), required=True)
    pdf_path = pdf_path or find_input_file(input_dir, (".pdf",))
    cfg = Config()

    # 1) Read the Excel metadata.
    try:
        records, schema = read_records(excel_path, cfg)
    except ValueError as exc:
        print(f"error: {exc}", file=sys.stderr)
        return 2
    print(f"Excel: {os.path.basename(excel_path)} -> {len(records)} rows "
          f"(orders {records[0].order}..{records[-1].order})")

    # 2) Extract the ZIP safely into a temp workdir.
    workdir = tempfile.mkdtemp(prefix="pw_task3_")
    try:
        extracted = extract_images(zip_path, workdir)
        images = extracted["images"]
        print(f"ZIP: {os.path.basename(zip_path)} -> {len(images)} images "
              f"({len(extracted['skipped'])} non-image entries skipped)")

        # 3) Choose the matching mode.
        has_image_cols = schema["qimg"] is not None and schema["simg"] is not None
        mode = "direct"
        fallback_result = None
        if force_fallback or not has_image_cols:
            if pdf_path is None:
                print("error: content fallback requires a PDF of the question paper "
                      "(--pdf or a .pdf in --input-dir)", file=sys.stderr)
                return 2
            mode = "fallback"
            print(f"PDF: {os.path.basename(pdf_path)} -> content-based matching")
            fallback_result, _per_image = match_by_content(records, images, pdf_path, cfg)
        else:
            print("PDF: not needed for the direct (Excel-mapping) mode")

        # 4) Audit integrity (always, so the 'is the ZIP usable?' verdict is evidenced).
        audit = audit_mod.run_audit(records, list(images.keys()), has_image_cols)
        tasks = renamer.build_tasks(records, images, cfg, mode, fallback_result)

        # 5) Execute the copy plan.
        renamer.execute(tasks, output_dir, dry_run)

        # 6) Report.
        os.makedirs(output_dir, exist_ok=True)
        report_path = os.path.join(output_dir, "report.csv")
        report_mod.write_report_csv(report_path, tasks)
        summary = report_mod.summarize(tasks, audit)
        report_mod.print_summary(summary, mode, schema)
        print(f"Manifest written to {report_path}")
        print(f"Output directory: {os.path.abspath(output_dir)}")
        return 0
    finally:
        if not keep_temp and os.path.isdir(workdir):
            shutil.rmtree(workdir, ignore_errors=True)


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--input-dir", default="input", help="directory with the PDF, ZIP and Excel")
    parser.add_argument("--output-dir", default="output", help="directory for renamed files")
    parser.add_argument("--zip", help="explicit path to the images ZIP (default: auto-detect)")
    parser.add_argument("--excel", help="explicit path to the metadata Excel (default: auto-detect)")
    parser.add_argument("--pdf", help="explicit path to the question paper PDF (default: auto-detect)")
    parser.add_argument("--force-fallback", action="store_true",
                        help="use content-based matching even if the Excel has image columns")
    parser.add_argument("--dry-run", action="store_true", help="compute the plan without copying")
    parser.add_argument("--keep-temp", action="store_true",
                        help="keep the extracted ZIP workdir (default: temp dir, cleaned up)")
    args = parser.parse_args()
    return run(
        input_dir=args.input_dir,
        output_dir=args.output_dir,
        zip_path=args.zip,
        excel_path=args.excel,
        pdf_path=args.pdf,
        force_fallback=args.force_fallback,
        dry_run=args.dry_run,
        keep_temp=args.keep_temp,
    )


if __name__ == "__main__":
    sys.exit(main())
