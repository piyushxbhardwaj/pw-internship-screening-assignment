"""Human-readable reporting: console summary + CSV manifest."""

import csv
from collections import Counter


def write_report_csv(path: str, tasks) -> None:
    with open(path, "w", newline="") as f:
        w = csv.writer(f)
        w.writerow(["display_order", "kind", "source_file", "output_file", "status", "note"])
        for t in sorted(tasks, key=lambda t: (t.order, t.kind)):
            w.writerow([t.order, t.kind, t.src_name, t.dst_name, t.status, t.note])


def summarize(tasks, audit) -> dict:
    status_counts = Counter(t.status for t in tasks)
    ok_statuses = ("ok", "copied", "dry_run")
    kinds = Counter(t.kind for t in tasks if t.status in ok_statuses)
    orders = {t.order for t in tasks}
    pairs_ok = sum(
        1 for o in orders
        if any(t.kind == "question" and t.status in ok_statuses for t in tasks if t.order == o)
        and any(t.kind == "solution" and t.status in ok_statuses for t in tasks if t.order == o)
    )
    return {
        "status_counts": dict(status_counts),
        "question_images_ok": kinds.get("question", 0),
        "solution_images_ok": kinds.get("solution", 0),
        "pairs_ok": pairs_ok,
        "total_orders": len(orders),
        "audit": audit,
    }


def print_summary(summary: dict, mode: str, schema: dict) -> None:
    print("=" * 72)
    print(f"Workflow mode: {mode}")
    print(f"Schema detected -> order col: {schema['order']!r}, "
          f"question-image col: {schema['qimg']!r}, solution-image col: {schema['simg']!r}")
    print("-" * 72)
    a = summary["audit"]
    print(f"Excel rows: {a.total_rows} | ZIP images: {a.total_zip_images}")
    if a.has_image_refs:
        print(f"Coverage: {a.coverage:.1%}" if a.coverage is not None else "Coverage: n/a")
        print(f"Referenced Q/S images missing from ZIP: "
              f"{len(a.q_refs_missing_in_zip) + len(a.s_refs_missing_in_zip)}")
        print(f"ZIP images not referenced by Excel: {len(a.unreferenced_in_zip)}")
        print(f"Duplicate references: {len(a.duplicate_refs)} | "
              f"contiguous orders: {a.orders_contiguous}")
    else:
        print("Coverage: n/a (Excel has no image columns; matching was content-based)")
    if a.order_gaps:
        print(f"Order gaps: {a.order_gaps}")
    print("-" * 72)
    for status, count in sorted(summary["status_counts"].items()):
        print(f"  {status:>18}: {count}")
    print(f"  {'question images produced':>18}: {summary['question_images_ok']}")
    print(f"  {'solution images produced':>18}: {summary['solution_images_ok']}")
    if summary["total_orders"]:
        pct = 100.0 * summary["pairs_ok"] / summary["total_orders"]
        print(f"  {'Q+S pairs produced':>18}: {summary['pairs_ok']}/{summary['total_orders']} ({pct:.0f}%)")
    print("=" * 72)
    print(f"VERDICT: {a.verdict()}")
