"""Verify that required paper artifacts exist before starting the paper track."""

from __future__ import annotations

import argparse
import csv
import json
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

from config import BASE_DIR, PAPER_DIR  # noqa: E402


REQUIRED_ARTIFACTS = [
    ("Architecture flowchart", "figures/architecture.png", "figure"),
    ("SMR taxonomy diagram", "figures/smr_taxonomy.png", "figure"),
    ("Seed sample table", "tables/seed_sample.csv", "table"),
    ("One-seed-to-variants example", "figures/variant_example.png", "figure"),
    ("Guardrail baseline sanity table", "tables/baseline.csv", "table"),
    ("MSIR per guardrail", "figures/msir_per_guardrail.png", "figure"),
    ("Guardrail x SMR heatmap", "figures/heatmap.png", "figure"),
    ("OWASP violation breakdown", "figures/owasp_breakdown.png", "figure"),
    ("Defense-gap plot", "figures/defense_gap.png", "figure"),
    ("Per-language/encoding breakdown", "figures/transform_breakdown.png", "figure"),
    ("Metamorphic-vs-flat baseline comparison", "figures/wedge_comparison.png", "figure"),
    ("McNemar significance + kappa summary", "tables/stats_summary.csv", "table"),
    ("McNemar paired baseline summary", "tables/mcnemar_summary.csv", "table"),
    ("Access-control leak example", "figures/access_control_example.png", "figure"),
    ("Before/after mitigation figure", "figures/mitigation.png", "figure"),
    ("Before/after mitigation table", "tables/mitigation.csv", "table"),
    ("Experiment runtime and cost summary", "tables/experiment_runtime_cost_summary.csv", "table"),
    ("Experiment platform summary", "tables/experiment_platform.csv", "table"),
    ("Results snapshot", "snapshots/run_snapshot.json", "snapshot"),
    ("Related-work positioning", "related_work.md", "paper_table"),
]

REQUIRED_CODE_ARTIFACTS = [
    ("Reproduction script", "reproduce.py"),
    ("Completeness checker", "src/check_paper_artifacts.py"),
    ("Run snapshot builder", "src/make_run_snapshot.py"),
    ("Experiment detail table builder", "src/make_experiment_details.py"),
    ("Seed-baseline builder", "src/make_seed_baseline.py"),
    ("McNemar computation", "src/compute_mcnemar.py"),
    ("Seed corpus", "data/seeds/seeds.jsonl"),
    ("README", "README.md"),
]


def pdf_companion(path: Path) -> Path:
    return path.with_suffix(".pdf")


def artifact_status(paper_dir: Path) -> list[dict[str, object]]:
    rows: list[dict[str, object]] = []
    for name, relative, kind in REQUIRED_ARTIFACTS:
        path = paper_dir / relative
        exists = path.exists() and path.stat().st_size > 0
        companion = ""
        companion_ok: bool | str = ""
        if kind == "figure":
            pdf = pdf_companion(path)
            companion = str(pdf)
            companion_ok = pdf.exists() and pdf.stat().st_size > 0
        rows.append(
            {
                "name": name,
                "kind": kind,
                "path": str(path),
                "exists": exists,
                "bytes": path.stat().st_size if path.exists() else 0,
                "pdf_companion": companion,
                "pdf_companion_exists": companion_ok,
                "ok": bool(exists and (companion_ok if kind == "figure" else True)),
            }
        )
    return rows


def code_status(root: Path) -> list[dict[str, object]]:
    rows: list[dict[str, object]] = []
    for name, relative in REQUIRED_CODE_ARTIFACTS:
        path = root / relative
        rows.append(
            {
                "name": name,
                "kind": "code",
                "path": str(path),
                "exists": path.exists() and path.stat().st_size > 0,
                "bytes": path.stat().st_size if path.exists() else 0,
                "pdf_companion": "",
                "pdf_companion_exists": "",
                "ok": path.exists() and path.stat().st_size > 0,
            }
        )
    return rows


def write_csv(path: Path, rows: list[dict[str, object]]) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    fields = [
        "name",
        "kind",
        "path",
        "exists",
        "bytes",
        "pdf_companion",
        "pdf_companion_exists",
        "ok",
    ]
    with path.open("w", encoding="utf-8", newline="") as handle:
        writer = csv.DictWriter(handle, fieldnames=fields, extrasaction="ignore")
        writer.writeheader()
        writer.writerows(rows)


def parse_args() -> argparse.Namespace:
    parser = argparse.ArgumentParser(description="Check paper artifact completeness.")
    parser.add_argument("--paper-dir", type=Path, default=PAPER_DIR)
    parser.add_argument("--root", type=Path, default=BASE_DIR)
    parser.add_argument(
        "--output",
        type=Path,
        default=PAPER_DIR / "tables" / "paper_data_completeness.csv",
    )
    return parser.parse_args()


def main() -> None:
    args = parse_args()
    rows = artifact_status(args.paper_dir) + code_status(args.root)
    write_csv(args.output, rows)
    missing = [row for row in rows if not row["ok"]]
    summary = {
        "checked": len(rows),
        "missing": len(missing),
        "output": str(args.output),
        "missing_names": [row["name"] for row in missing],
    }
    print(json.dumps(summary, ensure_ascii=True, indent=2))
    if missing:
        raise SystemExit(1)


if __name__ == "__main__":
    main()
