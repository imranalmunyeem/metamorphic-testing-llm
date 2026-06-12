"""Compute manual validation agreement for the spot-check CSV."""

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
    with path.open("r", encoding="utf-8", newline="") as handle:
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
    observed = sum(1 for model, human in pairs if model == human) / n
    model_counts = Counter(model for model, _ in pairs)
    human_counts = Counter(human for _, human in pairs)
    expected = sum((model_counts[label] / n) * (human_counts[label] / n) for label in [True, False])
    if expected == 1.0:
        return ("", "undefined_expected_agreement_1.0_single_class")
    return (f"{(observed - expected) / (1 - expected):.6f}", "computed")


def parse_args() -> argparse.Namespace:
    parser = argparse.ArgumentParser(description="Compute human/model validation agreement.")
    parser.add_argument(
        "--input",
        type=Path,
        default=PAPER_DIR / "tables" / "manual_variant_spotcheck.csv",
    )
    parser.add_argument(
        "--output",
        type=Path,
        default=PAPER_DIR / "tables" / "manual_agreement_summary.csv",
    )
    parser.add_argument(
        "--model-label-column",
        default="model_valid",
        help=(
            "Column containing model labels. If absent, all rows are treated as model_valid=true "
            "because the current spot-check sheet was sampled from accepted variants."
        ),
    )
    return parser.parse_args()


def main() -> None:
    args = parse_args()
    rows = read_csv(args.input)
    labeled_rows = [row for row in rows if str(row.get("human_valid", "")).strip()]
    if not labeled_rows:
        raise SystemExit("No human_valid labels found.")

    pairs: list[tuple[bool, bool]] = []
    for row in labeled_rows:
        model_raw = row.get(args.model_label_column, "true")
        pairs.append((as_bool(model_raw), as_bool(row["human_valid"])))

    total = len(pairs)
    agree = sum(1 for model, human in pairs if model == human)
    model_true = sum(1 for model, _ in pairs if model)
    model_false = total - model_true
    human_true = sum(1 for _, human in pairs if human)
    human_false = total - human_true
    tp = sum(1 for model, human in pairs if model and human)
    tn = sum(1 for model, human in pairs if not model and not human)
    fp = sum(1 for model, human in pairs if model and not human)
    fn = sum(1 for model, human in pairs if not model and human)
    kappa, kappa_status = cohen_kappa(pairs)

    summary = [
        {"metric": "manual_labeled_rows", "value": total, "note": "Rows with human_valid populated."},
        {"metric": "manual_raw_agreement", "value": f"{agree / total:.6f}", "note": "Model-human agreement."},
        {"metric": "manual_cohen_kappa", "value": kappa, "note": kappa_status},
        {"metric": "model_valid_true", "value": model_true, "note": ""},
        {"metric": "model_valid_false", "value": model_false, "note": ""},
        {"metric": "human_valid_true", "value": human_true, "note": ""},
        {"metric": "human_valid_false", "value": human_false, "note": ""},
        {"metric": "true_positive", "value": tp, "note": "Model valid and human valid."},
        {"metric": "true_negative", "value": tn, "note": "Model invalid and human invalid."},
        {"metric": "false_positive", "value": fp, "note": "Model valid, human invalid."},
        {"metric": "false_negative", "value": fn, "note": "Model invalid, human valid."},
    ]
    write_csv(args.output, summary, ["metric", "value", "note"])
    print(f"wrote={args.output}")
    print(f"kappa_status={kappa_status}")


if __name__ == "__main__":
    main()
