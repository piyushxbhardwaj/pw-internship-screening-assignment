"""Tests for the Task 03 workflow.

Run with:  pytest tests/ -v   (from the task3/ directory)
The suite uses synthetic fixtures under fixtures/synthetic/ so it runs
anywhere without the real PW batch files.
"""

import os
import shutil
import sys
import zipfile

import pytest

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

from src import audit as audit_mod
from src import renamer
from src.audit import run_audit
from src.config import Config
from src.excel_reader import read_records
from src.fallback import extract_blocks, match_by_content
from src.zip_reader import extract_images

FIXTURES = os.path.join(os.path.dirname(os.path.dirname(os.path.abspath(__file__))),
                        "fixtures", "synthetic")


@pytest.fixture(scope="module")
def fixtures_present():
    for sub in ("with_mapping", "no_mapping", "edge_cases"):
        d = os.path.join(FIXTURES, sub)
        assert os.path.isfile(os.path.join(d, "metadata.xlsx"))
        assert os.path.isfile(os.path.join(d, "images.zip"))
        assert os.path.isfile(os.path.join(d, "question_paper.pdf"))


# --------------------------------------------------------------------------
# Unit tests
# --------------------------------------------------------------------------

def test_extract_blocks_parses_fixture_pdf(fixtures_present):
    blocks = extract_blocks(os.path.join(FIXTURES, "with_mapping", "question_paper.pdf"))
    assert sorted(blocks.keys()) == [1, 2, 3, 4, 5]
    assert "New Delhi" in blocks[1]["solution"]
    assert "Newton" in blocks[2]["question"]


def test_zip_slip_is_rejected(tmp_path):
    evil = tmp_path / "evil.zip"
    with zipfile.ZipFile(evil, "w") as zf:
        zf.writestr("../../evil.png", b"pwned")
        zf.writestr("ok.png", b"fine")
    with pytest.raises(ValueError):
        extract_images(str(evil), str(tmp_path / "dest"))


def test_zip_skips_non_images(fixtures_present):
    d = os.path.join(FIXTURES, "with_mapping")
    work = tmp_out()
    try:
        out = extract_images(os.path.join(d, "images.zip"), work)
        assert len(out["images"]) == 10
        assert all(n.lower().endswith(".png") for n in out["images"])
    finally:
        shutil.rmtree(work, ignore_errors=True)


def test_schema_detection_mapping(fixtures_present):
    cfg = Config()
    _, schema = read_records(os.path.join(FIXTURES, "with_mapping", "metadata.xlsx"), cfg)
    assert schema == {"order": 0, "qimg": 2, "simg": 3}


def test_schema_detection_no_mapping(fixtures_present):
    cfg = Config()
    _, schema = read_records(os.path.join(FIXTURES, "no_mapping", "metadata.xlsx"), cfg)
    assert schema == {"order": 0, "qimg": None, "simg": None}


def test_schema_detection_variant_headers():
    cfg = Config()
    header = ["Q.No", "Topic", "Question Image URL", "Solution Image File", "Marks"]
    schema = cfg.detect_columns(header)
    assert schema["order"] == 0
    assert schema["qimg"] == 2
    assert schema["simg"] == 3


# --------------------------------------------------------------------------
# Integration tests
# --------------------------------------------------------------------------

def tmp_out():
    import tempfile
    return tempfile.mkdtemp(prefix="pw_test_out_")


def _run_pipeline(input_dir, output_dir, force_fallback=False):
    from rename_workflow import run
    code = run(
        input_dir=input_dir,
        output_dir=output_dir,
        force_fallback=force_fallback,
    )
    assert code == 0
    return output_dir


def _zip_bytes(zip_path, name):
    with zipfile.ZipFile(zip_path) as zf:
        return zf.read(name)


def test_direct_roundtrip_bytes_match(fixtures_present):
    d = os.path.join(FIXTURES, "with_mapping")
    out = _run_pipeline(d, tmp_out())
    records, schema = read_records(os.path.join(d, "metadata.xlsx"), Config())
    for rec in records:
        for kind, attr, prefix in (("Q", "question_image", "Q"), ("S", "solution_image", "S")):
            out_name = f"{prefix}{rec.order}.png"
            assert os.path.isfile(os.path.join(out, out_name)), f"missing {out_name}"
            expected = _zip_bytes(os.path.join(d, "images.zip"), getattr(rec, attr))
            actual = open(os.path.join(out, out_name), "rb").read()
            assert expected == actual, f"{out_name} content mismatch"


def test_direct_pipeline_statuses_all_copied(fixtures_present):
    d = os.path.join(FIXTURES, "with_mapping")
    out = _run_pipeline(d, tmp_out())
    import csv
    rows = list(csv.DictReader(open(os.path.join(out, "report.csv"))))
    assert len(rows) == 10
    assert all(r["status"] == "copied" for r in rows)


def test_fallback_roundtrip_produces_all_pairs(fixtures_present):
    d = os.path.join(FIXTURES, "no_mapping")
    out = _run_pipeline(d, tmp_out(), force_fallback=True)
    for i in range(1, 6):
        assert os.path.isfile(os.path.join(out, f"Q{i}.png")), f"missing Q{i}.png"
        assert os.path.isfile(os.path.join(out, f"S{i}.png")), f"missing S{i}.png"


def test_fallback_does_not_need_excel_image_columns(fixtures_present):
    d = os.path.join(FIXTURES, "no_mapping")
    out = tmp_out()
    from rename_workflow import run
    assert run(input_dir=d, output_dir=out) == 0  # auto-falls back to content matching


def test_audit_detects_missing_and_unreferenced(fixtures_present):
    d = os.path.join(FIXTURES, "edge_cases")
    records, schema = read_records(os.path.join(d, "metadata.xlsx"), Config())
    work = tmp_out()
    try:
        images = extract_images(os.path.join(d, "images.zip"), work)["images"]
    finally:
        shutil.rmtree(work, ignore_errors=True)
    a = run_audit(records, list(images.keys()), has_image_refs=True)
    assert len(a.q_refs_missing_in_zip) == 1
    assert len(a.unreferenced_in_zip) == 2
    assert a.coverage == pytest.approx(0.8)
    assert "PARTIALLY USABLE" in a.verdict()


def test_edge_case_report_flags_issues(fixtures_present):
    d = os.path.join(FIXTURES, "edge_cases")
    out = _run_pipeline(d, tmp_out())
    import csv
    rows = list(csv.DictReader(open(os.path.join(out, "report.csv"))))
    statuses = {r["status"] for r in rows}
    assert "missing_in_zip" in statuses


# --------------------------------------------------------------------------
# Real-batch test (skipped automatically when the real files are absent)
# --------------------------------------------------------------------------

REAL_DIR = os.path.join(os.path.dirname(os.path.dirname(os.path.abspath(__file__))), "input")


def test_real_batch_direct_if_present():
    if not os.path.isdir(REAL_DIR):
        pytest.skip("real PW batch not present")
    out = _run_pipeline(REAL_DIR, tmp_out())
    assert len(os.listdir(out)) >= 150
