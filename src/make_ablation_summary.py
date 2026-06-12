"""Summarize canonicalization ablation metrics for paper tables."""

from __future__ import annotations

import argparse
import csv
from pathlib import Path

import sys

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

from config import PAPER_DIR, RESULTS_DIR  # noqa: E402


def read_csv(path: Path) -> list[dict[str, str]]:
    if not path.exists():
        return []
    with path.open("r", encoding="utf-8", newline="") as handle:
        return list(csv.DictReader(handle))


def write_csv(path: Path, rows: list[dict[str, object]], fieldnames: list[str]) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    with path.open("w", encoding="utf-8", newline="") as handle:
        writer = csv.DictWriter(handle, fieldnames=fieldnames, extrasaction="ignore")
        writer.writeheader()
        writer.writerows(rows)


def first_float(rows: list[dict[str, str]], field: str) -> float | None:
    if not rows:
        return None
    value = rows[0].get(field, "")
    if value == "":
        return None
    return float(value)


def condition_overall(name: str, label: str, tables_dir: Path, baseline_msir: float | None) -> dict[str, object]:
    rows = read_csv(tables_dir / "msir_overall.csv")
    msir = first_float(rows, "mean")
    if msir is None:
        return {
            "condition": name,
            "label": label,
            "status": "missing",
            "msir": "",
            "ci95_low": "",
            "ci95_high": "",
            "absolute_drop_vs_baseline": "",
            "relative_drop_vs_baseline": "",
            "n_seed_smr_sets": "",
            "inconsistent_sets": "",
        }
    absolute_drop = "" if baseline_msir is None else baseline_msir - msir
    relative_drop = "" if baseline_msir in {None, 0.0} else absolute_drop / baseline_msir
    return {
        "condition": name,
        "label": label,
        "status": "computed",
        "msir": round(msir, 6),
        "ci95_low": rows[0].get("ci95_low", ""),
        "ci95_high": rows[0].get("ci95_high", ""),
        "absolute_drop_vs_baseline": "" if absolute_drop == "" else round(float(absolute_drop), 6),
        "relative_drop_vs_baseline": "" if relative_drop == "" else round(float(relative_drop), 6),
        "n_seed_smr_sets": rows[0].get("n_seed_smr_sets", ""),
        "inconsistent_sets": rows[0].get("inconsistent_sets", ""),
    }


def guardrail_rows(
    condition: str,
    label: str,
    tables_dir: Path,
    baseline_by_guardrail: dict[str, float],
) -> list[dict[str, object]]:
    rows = []
    for row in read_csv(tables_dir / "msir_by_guardrail.csv"):
        guardrail = row["guardrail"]
        msir = float(row["mean"])
        baseline = baseline_by_guardrail.get(guardrail)
        absolute_drop = "" if baseline is None else baseline - msir
        relative_drop = "" if baseline in {None, 0.0} else absolute_drop / baseline
        rows.append(
            {
                "condition": condition,
                "label": label,
                "guardrail": guardrail,
                "msir": round(msir, 6),
                "ci95_low": row.get("ci95_low", ""),
                "ci95_high": row.get("ci95_high", ""),
                "absolute_drop_vs_baseline": "" if absolute_drop == "" else round(float(absolute_drop), 6),
                "relative_drop_vs_baseline": "" if relative_drop == "" else round(float(relative_drop), 6),
                "n_seed_smr_sets": row.get("n_seed_smr_sets", ""),
                "inconsistent_sets": row.get("inconsistent_sets", ""),
            }
        )
    return rows


def parse_condition(value: str) -> tuple[str, str, Path]:
    parts = value.split("=", 2)
    if len(parts) != 3:
        raise argparse.ArgumentTypeError("conditions must be name=label=path")
    return parts[0], parts[1], Path(parts[2])


def parse_args() -> argparse.Namespace:
    parser = argparse.ArgumentParser(description="Build canonicalization ablation summary tables.")
    parser.add_argument(
        "--condition",
        action="append",
        type=parse_condition,
        default=None,
        help="Condition as name=label=tables_dir. Defaults to none, deterministic_only, full.",
    )
    parser.add_argument("--paper-dir", type=Path, default=PAPER_DIR)
    return parser.parse_args()


def main() -> None:
    args = parse_args()
    conditions = args.condition or [
        ("none", "No canonicalization", RESULTS_DIR / "tables"),
        ("deterministic_only", "Deterministic normalization only", RESULTS_DIR / "tables_ablation_deterministic"),
        ("full", "Deterministic normalization + translation", RESULTS_DIR / "tables_mitigated"),
    ]
    baseline_rows = read_csv(conditions[0][2] / "msir_by_guardrail.csv")
    baseline_by_guardrail = {row["guardrail"]: float(row["mean"]) for row in baseline_rows}
    baseline_msir = first_float(read_csv(conditions[0][2] / "msir_overall.csv"), "mean")

    overall = [
        condition_overall(name, label, tables_dir, baseline_msir)
        for name, label, tables_dir in conditions
    ]
    by_guardrail: list[dict[str, object]] = []
    for name, label, tables_dir in conditions:
        by_guardrail.extend(guardrail_rows(name, label, tables_dir, baseline_by_guardrail))

    tables_dir = args.paper_dir / "tables"
    write_csv(
        tables_dir / "canonicalization_ablation.csv",
        overall,
        [
            "condition",
            "label",
            "status",
            "msir",
            "ci95_low",
            "ci95_high",
            "absolute_drop_vs_baseline",
            "relative_drop_vs_baseline",
            "n_seed_smr_sets",
            "inconsistent_sets",
        ],
    )
    write_csv(
        tables_dir / "canonicalization_ablation_by_guardrail.csv",
        by_guardrail,
        [
            "condition",
            "label",
            "guardrail",
            "msir",
            "ci95_low",
            "ci95_high",
            "absolute_drop_vs_baseline",
            "relative_drop_vs_baseline",
            "n_seed_smr_sets",
            "inconsistent_sets",
        ],
    )
    print(f"wrote={tables_dir / 'canonicalization_ablation.csv'}")
    print(f"wrote={tables_dir / 'canonicalization_ablation_by_guardrail.csv'}")


if __name__ == "__main__":
    main()
