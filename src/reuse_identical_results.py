"""Reuse baseline verdicts when an ablation leaves variant text unchanged."""

from __future__ import annotations

import argparse
import json
from pathlib import Path

import sys

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

from config import RAW_RESULTS_DIR, VARIANT_DIR  # noqa: E402


def load_jsonl(path: Path) -> list[dict[str, object]]:
    if not path.exists():
        return []
    return [json.loads(line) for line in path.read_text(encoding="utf-8").splitlines() if line.strip()]


def append_jsonl(path: Path, rows: list[dict[str, object]]) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    with path.open("a", encoding="utf-8", newline="\n") as handle:
        for row in rows:
            handle.write(json.dumps(row, ensure_ascii=True, default=str) + "\n")


def key(row: dict[str, object]) -> tuple[str, str, int]:
    return (str(row["variant_id"]), str(row["guardrail"]), int(row.get("repetition", 1)))


def parse_args() -> argparse.Namespace:
    parser = argparse.ArgumentParser(description="Copy baseline results for unchanged ablation inputs.")
    parser.add_argument("--baseline-variants", type=Path, default=VARIANT_DIR / "variants.jsonl")
    parser.add_argument("--ablation-variants", type=Path, required=True)
    parser.add_argument("--baseline-results", type=Path, default=RAW_RESULTS_DIR / "results.jsonl")
    parser.add_argument("--ablation-results", type=Path, required=True)
    return parser.parse_args()


def main() -> None:
    args = parse_args()
    baseline_text = {
        str(row["variant_id"]): str(row.get("text", ""))
        for row in load_jsonl(args.baseline_variants)
    }
    ablation_rows = load_jsonl(args.ablation_variants)
    unchanged = {
        str(row["variant_id"])
        for row in ablation_rows
        if baseline_text.get(str(row["variant_id"])) == str(row.get("text", ""))
    }
    existing_keys = {key(row) for row in load_jsonl(args.ablation_results)}
    copied: list[dict[str, object]] = []
    for row in load_jsonl(args.baseline_results):
        if str(row.get("variant_id")) not in unchanged:
            continue
        row_key = key(row)
        if row_key in existing_keys:
            continue
        out = dict(row)
        out["reused_from_baseline_identical_input"] = True
        copied.append(out)
        existing_keys.add(row_key)
    append_jsonl(args.ablation_results, copied)
    print(
        json.dumps(
            {
                "unchanged_variants": len(unchanged),
                "copied_result_rows": len(copied),
                "ablation_results": str(args.ablation_results),
            },
            indent=2,
        )
    )


if __name__ == "__main__":
    main()
