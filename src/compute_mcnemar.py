"""Compute paired McNemar tests from seed-baseline and variant verdicts."""

from __future__ import annotations

import argparse
import csv
import json
import math
from collections import defaultdict
from pathlib import Path
from typing import Iterable

import sys

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

from config import PAPER_DIR, RAW_RESULTS_DIR, RESULTS_DIR, VARIANT_DIR  # noqa: E402


def load_jsonl(path: Path) -> list[dict[str, object]]:
    if not path.exists():
        return []
    return [json.loads(line) for line in path.read_text(encoding="utf-8").splitlines() if line.strip()]


def write_csv(path: Path, rows: list[dict[str, object]], fieldnames: list[str]) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    with path.open("w", encoding="utf-8", newline="") as handle:
        writer = csv.DictWriter(handle, fieldnames=fieldnames, extrasaction="ignore")
        writer.writeheader()
        writer.writerows(rows)


def as_bool(value: object) -> bool:
    if isinstance(value, bool):
        return value
    if isinstance(value, str):
        return value.strip().lower() in {"1", "true", "yes", "blocked"}
    return bool(value)


def collapse_outcomes(rows: Iterable[dict[str, object]]) -> dict[tuple[str, str], dict[str, object]]:
    grouped: dict[tuple[str, str], list[dict[str, object]]] = defaultdict(list)
    for row in rows:
        grouped[(str(row.get("variant_id")), str(row.get("guardrail")))].append(row)

    outcomes: dict[tuple[str, str], dict[str, object]] = {}
    for (variant_id, guardrail), group_rows in grouped.items():
        blocks = [1 if as_bool(row.get("blocked")) else 0 for row in group_rows]
        block_rate = sum(blocks) / len(blocks)
        first = group_rows[0]
        outcomes[(variant_id, guardrail)] = {
            "variant_id": variant_id,
            "guardrail": guardrail,
            "seed_id": str(first.get("seed_id", "")),
            "smr": str(first.get("smr", "")),
            "transformation": str(first.get("transformation", "")),
            "final_blocked": block_rate >= 0.5,
            "block_rate": round(block_rate, 6),
            "repetitions_observed": len(group_rows),
        }
    return outcomes


def exact_mcnemar_p_value(seed_block_variant_allow: int, seed_allow_variant_block: int) -> float:
    discordant = seed_block_variant_allow + seed_allow_variant_block
    if discordant == 0:
        return 1.0
    tail = min(seed_block_variant_allow, seed_allow_variant_block)
    probability = sum(math.comb(discordant, k) * (0.5**discordant) for k in range(tail + 1))
    return min(1.0, 2.0 * probability)


def mcnemar_chi_square(seed_block_variant_allow: int, seed_allow_variant_block: int) -> float:
    discordant = seed_block_variant_allow + seed_allow_variant_block
    if discordant == 0:
        return 0.0
    return ((abs(seed_block_variant_allow - seed_allow_variant_block) - 1) ** 2) / discordant


def compact_p_value(value: float) -> float:
    return float(f"{value:.12g}")


def summarize_group(name: tuple[str, ...], rows: list[dict[str, object]], fields: list[str]) -> dict[str, object]:
    both_block = sum(1 for row in rows if row["seed_blocked"] and row["variant_blocked"])
    both_allow = sum(1 for row in rows if not row["seed_blocked"] and not row["variant_blocked"])
    seed_block_variant_allow = sum(1 for row in rows if row["seed_blocked"] and not row["variant_blocked"])
    seed_allow_variant_block = sum(1 for row in rows if not row["seed_blocked"] and row["variant_blocked"])
    discordant = seed_block_variant_allow + seed_allow_variant_block
    exact_p = exact_mcnemar_p_value(seed_block_variant_allow, seed_allow_variant_block)
    summary: dict[str, object] = {
        "paired_variants": len(rows),
        "both_block": both_block,
        "both_allow": both_allow,
        "seed_block_variant_allow": seed_block_variant_allow,
        "seed_allow_variant_block": seed_allow_variant_block,
        "discordant_pairs": discordant,
        "mcnemar_exact_p": compact_p_value(exact_p),
        "mcnemar_chi_square_cc": round(mcnemar_chi_square(seed_block_variant_allow, seed_allow_variant_block), 6),
        "odds_ratio_discordant": (
            round(seed_block_variant_allow / seed_allow_variant_block, 6)
            if seed_allow_variant_block
            else ("inf" if seed_block_variant_allow else "")
        ),
        "significant_0_05": exact_p < 0.05,
    }
    for field, value in zip(fields, name):
        summary[field] = value
    return summary


def build_pairs(
    seed_results: list[dict[str, object]],
    variant_results: list[dict[str, object]],
) -> list[dict[str, object]]:
    seed_outcomes = collapse_outcomes(seed_results)
    variant_outcomes = collapse_outcomes(variant_results)
    seed_by_seed_guardrail = {
        (outcome["seed_id"], outcome["guardrail"]): outcome
        for outcome in seed_outcomes.values()
    }

    pairs: list[dict[str, object]] = []
    for outcome in variant_outcomes.values():
        seed = seed_by_seed_guardrail.get((outcome["seed_id"], outcome["guardrail"]))
        if seed is None:
            continue
        pairs.append(
            {
                "guardrail": outcome["guardrail"],
                "smr": outcome["smr"],
                "seed_id": outcome["seed_id"],
                "variant_id": outcome["variant_id"],
                "transformation": outcome["transformation"],
                "seed_blocked": bool(seed["final_blocked"]),
                "variant_blocked": bool(outcome["final_blocked"]),
                "seed_block_rate": seed["block_rate"],
                "variant_block_rate": outcome["block_rate"],
            }
        )
    return sorted(pairs, key=lambda row: (row["guardrail"], row["smr"], row["seed_id"], row["variant_id"]))


def summarize_pairs(pairs: list[dict[str, object]], group_fields: list[str]) -> list[dict[str, object]]:
    grouped: dict[tuple[str, ...], list[dict[str, object]]] = defaultdict(list)
    for row in pairs:
        grouped[tuple(str(row[field]) for field in group_fields)].append(row)
    return sorted(
        [summarize_group(name, rows, group_fields) for name, rows in grouped.items()],
        key=lambda row: tuple(str(row.get(field, "")) for field in group_fields),
    )


def add_multiple_testing_corrections(rows: list[dict[str, object]]) -> list[dict[str, object]]:
    if not rows:
        return rows
    indexed = [
        (idx, float(row["mcnemar_exact_p"]))
        for idx, row in enumerate(rows)
    ]
    m = len(indexed)

    holm_adjusted = [1.0] * m
    running = 0.0
    for rank, (idx, p_value) in enumerate(sorted(indexed, key=lambda item: item[1]), start=1):
        adjusted = min(1.0, (m - rank + 1) * p_value)
        running = max(running, adjusted)
        holm_adjusted[idx] = running

    bh_adjusted = [1.0] * m
    running_bh = 1.0
    for rank, (idx, p_value) in reversed(
        list(enumerate(sorted(indexed, key=lambda item: item[1]), start=1))
    ):
        adjusted = min(running_bh, (m / rank) * p_value)
        running_bh = adjusted
        bh_adjusted[idx] = min(1.0, adjusted)

    corrected: list[dict[str, object]] = []
    for idx, row in enumerate(rows):
        out = dict(row)
        out["holm_p"] = compact_p_value(holm_adjusted[idx])
        out["holm_significant_0_05"] = holm_adjusted[idx] < 0.05
        out["bh_p"] = compact_p_value(bh_adjusted[idx])
        out["bh_significant_0_05"] = bh_adjusted[idx] < 0.05
        corrected.append(out)
    return corrected


def parse_args() -> argparse.Namespace:
    parser = argparse.ArgumentParser(description="Compute McNemar paired significance tables.")
    parser.add_argument("--seed-results", type=Path, default=RAW_RESULTS_DIR / "seed_baseline_results.jsonl")
    parser.add_argument("--variant-results", type=Path, default=RAW_RESULTS_DIR / "results.jsonl")
    parser.add_argument("--output-dir", type=Path, default=RESULTS_DIR / "tables")
    parser.add_argument("--paper-dir", type=Path, default=PAPER_DIR / "tables")
    parser.add_argument("--skip-paper-copy", action="store_true")
    return parser.parse_args()


def main() -> None:
    args = parse_args()
    pairs = build_pairs(load_jsonl(args.seed_results), load_jsonl(args.variant_results))
    overall = add_multiple_testing_corrections(summarize_pairs(pairs, ["guardrail"]))
    by_smr = add_multiple_testing_corrections(summarize_pairs(pairs, ["guardrail", "smr"]))
    fields = [
        "guardrail",
        "smr",
        "paired_variants",
        "both_block",
        "both_allow",
        "seed_block_variant_allow",
        "seed_allow_variant_block",
        "discordant_pairs",
        "mcnemar_exact_p",
        "mcnemar_chi_square_cc",
        "odds_ratio_discordant",
        "significant_0_05",
        "holm_p",
        "holm_significant_0_05",
        "bh_p",
        "bh_significant_0_05",
    ]
    overall_fields = [field for field in fields if field != "smr"]
    pair_fields = [
        "guardrail",
        "smr",
        "seed_id",
        "variant_id",
        "transformation",
        "seed_blocked",
        "variant_blocked",
        "seed_block_rate",
        "variant_block_rate",
    ]
    write_csv(args.output_dir / "mcnemar_summary.csv", overall, overall_fields)
    write_csv(args.output_dir / "mcnemar_by_smr.csv", by_smr, fields)
    write_csv(args.output_dir / "mcnemar_pairs.csv", pairs, pair_fields)
    if not args.skip_paper_copy:
        write_csv(args.paper_dir / "mcnemar_summary.csv", overall, overall_fields)
        write_csv(args.paper_dir / "mcnemar_by_smr.csv", by_smr, fields)
    print(
        json.dumps(
            {
                "seed_results": str(args.seed_results),
                "variant_results": str(args.variant_results),
                "paired_variants": len(pairs),
                "summary": str(args.paper_dir / "mcnemar_summary.csv") if not args.skip_paper_copy else str(args.output_dir / "mcnemar_summary.csv"),
            },
            indent=2,
        )
    )


if __name__ == "__main__":
    main()
