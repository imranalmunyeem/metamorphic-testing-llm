"""Compute second-annotator agreement from a completed validation CSV."""

from __future__ import annotations

import argparse
import csv
from collections import Counter
from pathlib import Path

import sys

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

from config import PAPER_DIR  # noqa: E402


TRUE_VALUES = {"1", "true", "t", "yes", "y", "valid", "v"}
FALSE_VALUES = {"0", "false", "f", "no", "n", "invalid", "i"}


def as_bool(value: str) -> bool:
    cleaned = str(value or "").strip().casefold()
    if cleaned in TRUE_VALUES:
        return True
    if cleaned in FALSE_VALUES:
        return False
    raise ValueError(f"Invalid boolean label: {value!r}")


def read_csv(path: Path) -> list[dict[str, str]]:
    with path.open("r", encoding="utf-8-sig", newline="") as handle:
        return list(csv.DictReader(handle))


def write_csv(path: Path, rows: list[dict[str, object]], fields: list[str]) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    with path.open("w", encoding="utf-8", newline="") as handle:
        writer = csv.DictWriter(handle, fieldnames=fields)
        writer.writeheader()
        writer.writerows(rows)


def cohen_kappa(pairs: list[tuple[bool, bool]]) -> tuple[str, str]:
    if not pairs:
        return ("", "no_labeled_rows")
    n = len(pairs)
    observed = sum(1 for left, right in pairs if left == right) / n
    left_counts = Counter(left for left, _ in pairs)
    right_counts = Counter(right for _, right in pairs)
    expected = sum((left_counts[label] / n) * (right_counts[label] / n) for label in [True, False])
    if expected == 1.0:
        return ("", "undefined_expected_agreement_1.0_single_class")
    return (f"{(observed - expected) / (1 - expected):.6f}", "computed")


def summarize(pairs: list[tuple[bool, bool]], left_name: str, right_name: str) -> list[dict[str, object]]:
    total = len(pairs)
    agree = sum(1 for left, right in pairs if left == right)
    kappa, status = cohen_kappa(pairs)
    left_true = sum(1 for left, _ in pairs if left)
    right_true = sum(1 for _, right in pairs if right)
    return [
        {"metric": f"{left_name}_vs_{right_name}_rows", "value": total, "note": ""},
        {"metric": f"{left_name}_vs_{right_name}_raw_agreement", "value": f"{agree / total:.6f}" if total else "", "note": ""},
        {"metric": f"{left_name}_vs_{right_name}_cohen_kappa", "value": kappa, "note": status},
        {"metric": f"{left_name}_true", "value": left_true, "note": ""},
        {"metric": f"{left_name}_false", "value": total - left_true, "note": ""},
        {"metric": f"{right_name}_true", "value": right_true, "note": ""},
        {"metric": f"{right_name}_false", "value": total - right_true, "note": ""},
    ]


def parse_args() -> argparse.Namespace:
    parser = argparse.ArgumentParser(description="Compute second annotator validation agreement.")
    parser.add_argument(
        "--completed",
        type=Path,
        default=PAPER_DIR / "tables" / "human_validation_second_annotator_completed.csv",
        help="Completed coworker CSV with human_valid populated.",
    )
    parser.add_argument(
        "--key",
        type=Path,
        default=PAPER_DIR / "tables" / "human_validation_second_annotator_internal_key.csv",
    )
    parser.add_argument(
        "--first",
        type=Path,
        default=PAPER_DIR / "tables" / "manual_variant_spotcheck.csv",
    )
    parser.add_argument(
        "--output",
        type=Path,
        default=PAPER_DIR / "tables" / "second_annotator_agreement_summary.csv",
    )
    return parser.parse_args()


def main() -> None:
    args = parse_args()
    completed = {row["variant_id"]: row for row in read_csv(args.completed) if row.get("human_valid")}
    key = {row["variant_id"]: row for row in read_csv(args.key)}
    first = {row["variant_id"]: row for row in read_csv(args.first) if row.get("human_valid")}

    validator_pairs: list[tuple[bool, bool]] = []
    annotator_pairs: list[tuple[bool, bool]] = []
    for variant_id, row in completed.items():
        if variant_id in key:
            validator_pairs.append((as_bool(key[variant_id]["validator_label"]), as_bool(row["human_valid"])))
        if variant_id in first:
            annotator_pairs.append((as_bool(first[variant_id]["human_valid"]), as_bool(row["human_valid"])))

    rows = []
    rows.extend(summarize(validator_pairs, "validator", "second_annotator"))
    rows.extend(summarize(annotator_pairs, "first_annotator", "second_annotator"))
    write_csv(args.output, rows, ["metric", "value", "note"])
    print(f"wrote={args.output}")


if __name__ == "__main__":
    main()
