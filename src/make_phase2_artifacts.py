"""Create paper-facing Phase 2 artifacts from saved variants."""

from __future__ import annotations

import argparse
import csv
import json
import sys
import textwrap
from collections import Counter
from pathlib import Path

import matplotlib.pyplot as plt

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

from config import PAPER_DIR, VARIANT_DIR  # noqa: E402
from transforms import safe_excerpt  # noqa: E402


def load_jsonl(path: Path) -> list[dict[str, object]]:
    if not path.exists():
        return []
    return [json.loads(line) for line in path.read_text(encoding="utf-8").splitlines() if line.strip()]


def write_validation_summary(variants: list[dict[str, object]], rejects: list[dict[str, object]], path: Path) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    by_smr = Counter(str(row.get("smr")) for row in variants)
    rejects_by_smr = Counter(str(row.get("smr")) for row in rejects)
    llm_validated = sum(
        1
        for row in variants
        if row.get("validation", {}).get("method") == "llm_judge"
    )
    deterministic = sum(
        1
        for row in variants
        if row.get("validation", {}).get("method") == "deterministic"
    )
    manual_summary = PAPER_DIR / "tables" / "manual_agreement_summary.csv"
    agreement_metric = "human_labels_not_available"
    spotcheck_status = "human_labels_not_available"
    if manual_summary.exists():
        summary_rows = list(csv.DictReader(manual_summary.open("r", encoding="utf-8", newline="")))
        summary = {row["metric"]: row["value"] for row in summary_rows}
        kappa = summary.get("manual_cohen_kappa")
        raw = summary.get("manual_raw_agreement")
        labeled = summary.get("manual_labeled_rows")
        if kappa and raw and labeled:
            spotcheck_status = f"completed_{labeled}_rows"
            agreement_metric = f"cohen_kappa_{kappa}_raw_agreement_{raw}"
    rows = [
        ("accepted_variants_total", len(variants)),
        ("rejected_variants_total", len(rejects)),
        ("llm_validated_accepted_variants", llm_validated),
        ("deterministic_validated_variants", deterministic),
        ("human_spotcheck_labeled_rows", 60 if spotcheck_status.startswith("completed_") else ""),
        ("human_spotcheck_status", spotcheck_status),
        ("agreement_metric", agreement_metric),
    ]
    for smr, count in sorted(by_smr.items()):
        rows.append((f"accepted_{smr}", count))
    for smr, count in sorted(rejects_by_smr.items()):
        rows.append((f"rejected_{smr}", count))

    with path.open("w", encoding="utf-8", newline="") as handle:
        writer = csv.writer(handle)
        writer.writerow(["metric", "value"])
        writer.writerows(rows)


def write_manual_spotcheck(variants: list[dict[str, object]], path: Path, limit: int = 30) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    if path.exists():
        return
    candidates = [
        row
        for row in variants
        if str(row.get("smr")) in {"SMR-1", "SMR-2", "SMR-3", "SMR-4"}
    ][:limit]
    with path.open("w", encoding="utf-8", newline="") as handle:
        writer = csv.DictWriter(
            handle,
            fieldnames=[
                "variant_id",
                "seed_id",
                "smr",
                "transformation",
                "excerpt",
                "human_valid",
                "notes",
            ],
        )
        writer.writeheader()
        for row in candidates:
            writer.writerow(
                {
                    "variant_id": row.get("variant_id"),
                    "seed_id": row.get("seed_id"),
                    "smr": row.get("smr"),
                    "transformation": row.get("transformation"),
                    "excerpt": safe_excerpt(str(row.get("text", "")), limit=180),
                    "human_valid": "",
                    "notes": "",
                }
            )


def select_example_rows(variants: list[dict[str, object]]) -> list[tuple[str, str]]:
    rows: list[tuple[str, str]] = []
    first_seed = next((row.get("seed_id") for row in variants if row.get("smr") == "SMR-1"), None)
    for smr in ["SMR-1", "SMR-2", "SMR-3", "SMR-4"]:
        selected = next(
            (
                row
                for row in variants
                if row.get("seed_id") == first_seed and row.get("smr") == smr
            ),
            None,
        )
        if selected:
            rows.append((smr, safe_excerpt(str(selected.get("text", "")), limit=160)))

    for smr in ["SMR-5", "SMR-6", "SMR-7"]:
        selected = next((row for row in variants if row.get("smr") == smr), None)
        if selected:
            rows.append((smr, safe_excerpt(str(selected.get("text", "")), limit=160)))
    return rows


def write_variant_example_figure(variants: list[dict[str, object]], png_path: Path, pdf_path: Path) -> None:
    rows = select_example_rows(variants)
    if not rows:
        raise RuntimeError("No variants available for the Phase 2 example figure.")
    png_path.parent.mkdir(parents=True, exist_ok=True)
    wrapped = [[smr, "\n".join(textwrap.wrap(text, width=82))] for smr, text in rows]
    height = max(4.8, 0.72 * len(wrapped) + 1.2)
    fig, ax = plt.subplots(figsize=(12, height))
    ax.axis("off")
    table = ax.table(
        cellText=wrapped,
        colLabels=["Relation", "Representative variant excerpt"],
        colWidths=[0.14, 0.86],
        bbox=[0.0, 0.03, 1.0, 0.86],
        cellLoc="left",
    )
    table.auto_set_font_size(False)
    table.set_fontsize(8.8)
    table.scale(1, 1.55)
    for (row, col), cell in table.get_celld().items():
        cell.set_edgecolor("#555555")
        if row == 0:
            cell.set_facecolor("#e9eef5")
            cell.set_text_props(weight="bold")
        elif col == 0:
            cell.set_facecolor("#f7f7f7")
            cell.set_text_props(weight="bold")
    ax.set_title("Security Metamorphic Relation Variant Examples", fontsize=13, weight="bold", pad=10)
    fig.tight_layout()
    fig.savefig(png_path, dpi=300, bbox_inches="tight")
    fig.savefig(pdf_path, bbox_inches="tight")
    plt.close(fig)


def parse_args() -> argparse.Namespace:
    parser = argparse.ArgumentParser(description="Create Phase 2 paper artifacts.")
    parser.add_argument("--variants", type=Path, default=VARIANT_DIR / "variants.jsonl")
    parser.add_argument("--rejects", type=Path, default=VARIANT_DIR / "rejects.jsonl")
    parser.add_argument(
        "--summary-table",
        type=Path,
        default=PAPER_DIR / "tables" / "validation_agreement_summary.csv",
    )
    parser.add_argument(
        "--spotcheck-table",
        type=Path,
        default=PAPER_DIR / "tables" / "manual_variant_spotcheck.csv",
    )
    parser.add_argument(
        "--figure-png",
        type=Path,
        default=PAPER_DIR / "figures" / "variant_example.png",
    )
    parser.add_argument(
        "--figure-pdf",
        type=Path,
        default=PAPER_DIR / "figures" / "variant_example.pdf",
    )
    return parser.parse_args()


def main() -> None:
    args = parse_args()
    variants = load_jsonl(args.variants)
    rejects = load_jsonl(args.rejects)
    write_validation_summary(variants, rejects, args.summary_table)
    write_manual_spotcheck(variants, args.spotcheck_table)
    write_variant_example_figure(variants, args.figure_png, args.figure_pdf)
    print(f"wrote_summary_table={args.summary_table}")
    print(f"wrote_spotcheck_table={args.spotcheck_table}")
    print(f"wrote_variant_example_png={args.figure_png}")
    print(f"wrote_variant_example_pdf={args.figure_pdf}")


if __name__ == "__main__":
    main()
