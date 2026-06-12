"""Apply author-provided human labels to the manual spot-check CSV."""

from __future__ import annotations

import argparse
import csv
from pathlib import Path

import sys

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

from config import PAPER_DIR  # noqa: E402


TRUE_VALUES = {"1", "true", "t", "yes", "y", "valid", "v"}
FALSE_VALUES = {"0", "false", "f", "no", "n", "invalid", "i"}


def normalize_label(value: str) -> str:
    cleaned = value.strip().casefold()
    if cleaned in TRUE_VALUES:
        return "true"
    if cleaned in FALSE_VALUES:
        return "false"
    raise ValueError(f"Unrecognized label: {value!r}. Use true/false or T/F.")


def parse_labels(raw: str) -> list[str]:
    return [normalize_label(item) for item in raw.replace("\n", ",").split(",") if item.strip()]


def read_rows(path: Path) -> list[dict[str, str]]:
    with path.open("r", encoding="utf-8", newline="") as handle:
        return list(csv.DictReader(handle))


def write_rows(path: Path, rows: list[dict[str, str]], fieldnames: list[str]) -> None:
    with path.open("w", encoding="utf-8", newline="") as handle:
        writer = csv.DictWriter(handle, fieldnames=fieldnames)
        writer.writeheader()
        writer.writerows(rows)


def parse_args() -> argparse.Namespace:
    parser = argparse.ArgumentParser(description="Apply manual true/false labels to spot-check rows.")
    parser.add_argument(
        "--input",
        type=Path,
        default=PAPER_DIR / "tables" / "manual_variant_spotcheck.csv",
    )
    parser.add_argument(
        "--labels",
        required=True,
        help="Comma-separated labels in row order, e.g. T,T,T,F,T.",
    )
    return parser.parse_args()


def main() -> None:
    args = parse_args()
    rows = read_rows(args.input)
    labels = parse_labels(args.labels)
    if len(labels) != len(rows):
        raise SystemExit(f"Expected {len(rows)} labels, got {len(labels)}.")

    for row, label in zip(rows, labels):
        row["human_valid"] = label

    fieldnames = list(rows[0].keys()) if rows else ["variant_id", "human_valid"]
    write_rows(args.input, rows, fieldnames)
    print(f"updated={args.input}")
    print(f"labels_applied={len(labels)}")


if __name__ == "__main__":
    main()
