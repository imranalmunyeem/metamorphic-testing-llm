"""Create Phase 4 paper-facing access-control artifact."""

from __future__ import annotations

import argparse
import csv
import re
import sys
import textwrap
from pathlib import Path

import matplotlib.pyplot as plt

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

from config import PAPER_DIR  # noqa: E402


def load_rows(path: Path) -> list[dict[str, str]]:
    with path.open("r", encoding="utf-8", newline="") as handle:
        return list(csv.DictReader(handle))


def wrap(text: str, width: int = 78) -> str:
    clean = re.sub(r"\*\*(.*?)\*\*", r"\1", str(text).replace("\n", " "))
    return "\n".join(textwrap.wrap(clean, width=width))


def make_example_figure(rows: list[dict[str, str]], scenario_id: str, png_path: Path, pdf_path: Path) -> None:
    selected = [row for row in rows if row["scenario_id"] == scenario_id]
    if len(selected) != 2:
        raise RuntimeError(f"Expected two rows for {scenario_id}, found {len(selected)}.")
    selected.sort(key=lambda row: 0 if row["role_level"] == "low" else 1)
    table_rows = []
    for row in selected:
        leaked = row["leaked_markers"] or "none"
        table_rows.append(
            [
                f"{row['role_level']} ({row['role']})",
                "\n".join(row["retrieved_doc_ids"].split("|")),
                leaked,
                wrap(row["answer"], width=88),
            ]
        )

    fig, ax = plt.subplots(figsize=(14, 5.6))
    ax.axis("off")
    table = ax.table(
        cellText=table_rows,
        colLabels=["Role", "Retrieved docs", "Restricted marker leaks", "Answer excerpt"],
        colWidths=[0.14, 0.16, 0.14, 0.56],
        bbox=[0.0, 0.02, 1.0, 0.84],
        cellLoc="left",
    )
    table.auto_set_font_size(False)
    table.set_fontsize(8.5)
    table.scale(1, 1.75)
    for (row, col), cell in table.get_celld().items():
        cell.set_edgecolor("#555555")
        if row == 0:
            cell.set_facecolor("#e9eef5")
            cell.set_text_props(weight="bold")
        elif col == 0:
            cell.set_facecolor("#f7f7f7")
            cell.set_text_props(weight="bold")
    ax.set_title(
        f"SMR-5 Access-Control Differential Example ({scenario_id})",
        fontsize=13,
        weight="bold",
        pad=10,
    )
    fig.tight_layout()
    png_path.parent.mkdir(parents=True, exist_ok=True)
    fig.savefig(png_path, dpi=300, bbox_inches="tight")
    fig.savefig(pdf_path, bbox_inches="tight")
    plt.close(fig)


def parse_args() -> argparse.Namespace:
    parser = argparse.ArgumentParser(description="Create Phase 4 paper artifacts.")
    parser.add_argument("--input", type=Path, default=PAPER_DIR / "tables" / "access_control_smoke.csv")
    parser.add_argument("--scenario-id", default="AC-001")
    parser.add_argument(
        "--png",
        type=Path,
        default=PAPER_DIR / "figures" / "access_control_example.png",
    )
    parser.add_argument(
        "--pdf",
        type=Path,
        default=PAPER_DIR / "figures" / "access_control_example.pdf",
    )
    return parser.parse_args()


def main() -> None:
    args = parse_args()
    rows = load_rows(args.input)
    make_example_figure(rows, args.scenario_id, args.png, args.pdf)
    print(f"wrote_access_control_example_png={args.png}")
    print(f"wrote_access_control_example_pdf={args.pdf}")


if __name__ == "__main__":
    main()
