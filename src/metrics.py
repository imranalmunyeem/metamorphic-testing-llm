"""Compute Phase 6 SMR consistency metrics from raw guardrail results."""

from __future__ import annotations

import argparse
import csv
import hashlib
import json
import math
import random
import statistics
import sys
from collections import Counter, defaultdict
from pathlib import Path
from typing import Iterable

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

from config import (  # noqa: E402
    LLM_REPETITIONS,
    PAPER_DIR,
    RANDOM_SEED,
    RAW_RESULTS_DIR,
    RESULTS_DIR,
    VARIANT_DIR,
)


REPETITIONS = {
    "regex_baseline": 1,
    "openai_moderation": 1,
    "protectai": 1,
    "llmguard": 1,
    "llm_judge": LLM_REPETITIONS,
}


def load_jsonl(path: Path) -> list[dict[str, object]]:
    if not path.exists():
        raise FileNotFoundError(f"Missing JSONL input: {path}")
    return [
        json.loads(line)
        for line in path.read_text(encoding="utf-8").splitlines()
        if line.strip()
    ]


def write_csv(path: Path, rows: list[dict[str, object]], fieldnames: list[str]) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    with path.open("w", encoding="utf-8", newline="") as handle:
        writer = csv.DictWriter(handle, fieldnames=fieldnames, extrasaction="ignore")
        writer.writeheader()
        for row in rows:
            writer.writerow(row)


def load_manual_agreement_summary() -> dict[str, str]:
    path = PAPER_DIR / "tables" / "manual_agreement_summary.csv"
    if not path.exists():
        return {}
    with path.open("r", encoding="utf-8", newline="") as handle:
        return {row["metric"]: row["value"] for row in csv.DictReader(handle)}


def load_mcnemar_summary(summary_dir: Path) -> list[dict[str, str]]:
    path = summary_dir / "mcnemar_summary.csv"
    if not path.exists():
        return []
    with path.open("r", encoding="utf-8", newline="") as handle:
        return list(csv.DictReader(handle))


def sorted_rows(rows: Iterable[dict[str, object]], keys: list[str]) -> list[dict[str, object]]:
    return sorted(rows, key=lambda row: tuple(str(row.get(key, "")) for key in keys))


def as_bool(value: object) -> bool:
    if isinstance(value, bool):
        return value
    if isinstance(value, str):
        return value.strip().lower() in {"1", "true", "yes", "blocked"}
    return bool(value)


def dedupe_results(rows: list[dict[str, object]]) -> tuple[list[dict[str, object]], int]:
    latest: dict[tuple[str, str, int], dict[str, object]] = {}
    duplicates = 0
    for row in rows:
        key = (
            str(row.get("variant_id")),
            str(row.get("guardrail")),
            int(row.get("repetition", 1)),
        )
        if key in latest:
            duplicates += 1
        latest[key] = row
    return list(latest.values()), duplicates


def variant_metadata(
    variants: list[dict[str, object]] | None,
    rows: list[dict[str, object]],
) -> dict[str, dict[str, object]]:
    metadata: dict[str, dict[str, object]] = {}
    source = variants if variants is not None else rows
    for row in source:
        variant_id = row.get("variant_id")
        if variant_id is None:
            continue
        metadata[str(variant_id)] = {
            "variant_id": str(variant_id),
            "seed_id": row.get("seed_id", ""),
            "smr": row.get("smr", ""),
            "transformation": row.get("transformation", ""),
            "relation_type": row.get("relation_type", ""),
            "owasp_category": row.get("owasp_category", ""),
        }
    return metadata


def collapse_variant_outcomes(
    rows: list[dict[str, object]],
    metadata: dict[str, dict[str, object]],
) -> list[dict[str, object]]:
    grouped: dict[tuple[str, str], list[dict[str, object]]] = defaultdict(list)
    for row in rows:
        grouped[(str(row.get("variant_id")), str(row.get("guardrail")))].append(row)

    outcomes: list[dict[str, object]] = []
    for (variant_id, guardrail), group_rows in grouped.items():
        blocks = [1.0 if as_bool(row.get("blocked")) else 0.0 for row in group_rows]
        block_rate = sum(blocks) / len(blocks)
        meta = metadata.get(variant_id, {})
        first = group_rows[0]
        outcomes.append(
            {
                "variant_id": variant_id,
                "guardrail": guardrail,
                "seed_id": meta.get("seed_id") or first.get("seed_id", ""),
                "smr": meta.get("smr") or first.get("smr", ""),
                "transformation": meta.get("transformation") or first.get("transformation", ""),
                "relation_type": meta.get("relation_type") or first.get("relation_type", ""),
                "owasp_category": meta.get("owasp_category") or first.get("owasp_category", ""),
                "repetitions_observed": len(group_rows),
                "block_rate": round(block_rate, 6),
                "final_blocked": block_rate >= 0.5,
            }
        )
    return sorted_rows(outcomes, ["guardrail", "seed_id", "smr", "variant_id"])


def expected_variant_counts(
    metadata: dict[str, dict[str, object]],
) -> Counter[tuple[str, str]]:
    counts: Counter[tuple[str, str]] = Counter()
    for row in metadata.values():
        counts[(str(row.get("seed_id")), str(row.get("smr")))] += 1
    return counts


def build_group_metrics(
    outcomes: list[dict[str, object]],
    expected_counts: Counter[tuple[str, str]],
) -> list[dict[str, object]]:
    grouped: dict[tuple[str, str, str], list[dict[str, object]]] = defaultdict(list)
    for row in outcomes:
        grouped[(str(row["guardrail"]), str(row["seed_id"]), str(row["smr"]))].append(row)

    metrics: list[dict[str, object]] = []
    for (guardrail, seed_id, smr), group_rows in grouped.items():
        if len(group_rows) < 2:
            continue
        final_verdicts = [bool(row["final_blocked"]) for row in group_rows]
        block_rates = [float(row["block_rate"]) for row in group_rows]
        expected = expected_counts.get((seed_id, smr), len(group_rows))
        inconsistent = len(set(final_verdicts)) > 1
        metrics.append(
            {
                "guardrail": guardrail,
                "seed_id": seed_id,
                "smr": smr,
                "relation_type": group_rows[0].get("relation_type", ""),
                "owasp_category": group_rows[0].get("owasp_category", ""),
                "variants_observed": len(group_rows),
                "variants_expected": expected,
                "coverage_rate": round(len(group_rows) / expected, 6) if expected else 0.0,
                "complete_set": len(group_rows) >= expected,
                "inconsistent": inconsistent,
                "inconsistent_int": 1 if inconsistent else 0,
                "blocked_variants": sum(1 for verdict in final_verdicts if verdict),
                "allowed_variants": sum(1 for verdict in final_verdicts if not verdict),
                "block_rate_min": round(min(block_rates), 6),
                "block_rate_max": round(max(block_rates), 6),
                "defense_gap": round(max(block_rates) - min(block_rates), 6),
            }
        )
    return sorted_rows(metrics, ["guardrail", "smr", "seed_id"])


def bootstrap_mean_ci(
    values: list[float],
    iterations: int,
    rng: random.Random,
) -> tuple[float, float, float]:
    if not values:
        return (math.nan, math.nan, math.nan)
    estimate = sum(values) / len(values)
    if len(values) == 1 or iterations <= 0:
        return (estimate, estimate, estimate)
    sampled: list[float] = []
    n = len(values)
    for _ in range(iterations):
        sampled.append(sum(values[rng.randrange(n)] for _ in range(n)) / n)
    sampled.sort()
    low_idx = int(0.025 * (iterations - 1))
    high_idx = int(0.975 * (iterations - 1))
    return (estimate, sampled[low_idx], sampled[high_idx])


def summarize_indicator(
    rows: list[dict[str, object]],
    group_fields: list[str],
    value_field: str,
    output_name: str,
    iterations: int,
    seed: int,
) -> list[dict[str, object]]:
    grouped: dict[tuple[object, ...], list[dict[str, object]]] = defaultdict(list)
    if group_fields:
        for row in rows:
            grouped[tuple(row.get(field, "") for field in group_fields)].append(row)
    else:
        grouped[("overall",)].extend(rows)

    summary_rows: list[dict[str, object]] = []
    for key, group_rows in grouped.items():
        values = [float(row[value_field]) for row in group_rows]
        digest = hashlib.sha256(repr((output_name, key)).encode("utf-8")).hexdigest()
        rng = random.Random(seed + int(digest[:12], 16))
        estimate, ci_low, ci_high = bootstrap_mean_ci(values, iterations, rng)
        summary = {
            "summary": output_name,
            "n_seed_smr_sets": len(group_rows),
            "inconsistent_sets": int(sum(values)) if value_field == "inconsistent_int" else "",
            "mean": round(estimate, 6),
            "ci95_low": round(ci_low, 6),
            "ci95_high": round(ci_high, 6),
            "complete_sets": sum(1 for row in group_rows if row.get("complete_set") is True),
            "incomplete_sets": sum(1 for row in group_rows if row.get("complete_set") is not True),
            "observed_variants": sum(int(row.get("variants_observed", 0)) for row in group_rows),
            "expected_variants": sum(int(row.get("variants_expected", 0)) for row in group_rows),
        }
        for field, value in zip(group_fields or ["scope"], key):
            summary[field] = value
        summary_rows.append(summary)
    return sorted_rows(summary_rows, group_fields or ["scope"])


def coverage_summary(
    rows: list[dict[str, object]],
    metadata: dict[str, dict[str, object]],
    duplicates_removed: int,
) -> list[dict[str, object]]:
    by_guardrail = Counter(str(row.get("guardrail")) for row in rows)
    variants_by_guardrail: dict[str, set[str]] = defaultdict(set)
    reps_by_guardrail_variant: dict[tuple[str, str], set[int]] = defaultdict(set)
    for row in rows:
        guardrail = str(row.get("guardrail"))
        variant_id = str(row.get("variant_id"))
        variants_by_guardrail[guardrail].add(variant_id)
        reps_by_guardrail_variant[(guardrail, variant_id)].add(int(row.get("repetition", 1)))

    guardrails = sorted(set(REPETITIONS) | set(by_guardrail))
    expected_variants = len(metadata)
    summary: list[dict[str, object]] = []
    for guardrail in guardrails:
        expected_repetitions = REPETITIONS.get(guardrail, 1)
        expected_rows = expected_variants * expected_repetitions
        observed_rows = by_guardrail.get(guardrail, 0)
        observed_variants = len(variants_by_guardrail.get(guardrail, set()))
        complete_variants = sum(
            1
            for variant_id in variants_by_guardrail.get(guardrail, set())
            if len(reps_by_guardrail_variant[(guardrail, variant_id)]) >= expected_repetitions
        )
        summary.append(
            {
                "guardrail": guardrail,
                "expected_variants": expected_variants,
                "observed_variants": observed_variants,
                "expected_repetitions": expected_repetitions,
                "expected_rows": expected_rows,
                "observed_rows": observed_rows,
                "missing_rows": max(0, expected_rows - observed_rows),
                "row_coverage_rate": round(observed_rows / expected_rows, 6) if expected_rows else 0.0,
                "complete_variants": complete_variants,
                "duplicates_removed": duplicates_removed,
            }
        )
    return summary


def flat_detection_summary(
    outcomes: list[dict[str, object]],
    group_fields: list[str],
) -> list[dict[str, object]]:
    grouped: dict[tuple[object, ...], list[dict[str, object]]] = defaultdict(list)
    for row in outcomes:
        grouped[tuple(row.get(field, "") for field in group_fields)].append(row)

    rows: list[dict[str, object]] = []
    for key, group_rows in grouped.items():
        block_rates = [float(row["block_rate"]) for row in group_rows]
        row = {
            "variant_outcomes": len(group_rows),
            "blocked_outcomes": sum(1 for item in group_rows if item["final_blocked"]),
            "flat_block_rate": round(sum(1 for item in group_rows if item["final_blocked"]) / len(group_rows), 6),
            "mean_repetition_block_rate": round(sum(block_rates) / len(block_rates), 6),
        }
        for field, value in zip(group_fields, key):
            row[field] = value
        rows.append(row)
    return sorted_rows(rows, group_fields)


def nondeterminism_summary(rows: list[dict[str, object]]) -> list[dict[str, object]]:
    grouped: dict[tuple[str, str], list[dict[str, object]]] = defaultdict(list)
    for row in rows:
        grouped[(str(row.get("guardrail")), str(row.get("variant_id")))].append(row)

    by_guardrail: dict[str, list[list[int]]] = defaultdict(list)
    for (guardrail, _variant_id), group_rows in grouped.items():
        if len(group_rows) <= 1:
            continue
        verdicts = [1 if as_bool(row.get("blocked")) else 0 for row in group_rows]
        by_guardrail[guardrail].append(verdicts)

    summary: list[dict[str, object]] = []
    for guardrail, verdict_lists in sorted(by_guardrail.items()):
        variances = [statistics.pvariance(values) for values in verdict_lists]
        nondeterministic = sum(1 for values in verdict_lists if len(set(values)) > 1)
        summary.append(
            {
                "guardrail": guardrail,
                "variants_with_repetitions": len(verdict_lists),
                "nondeterministic_variants": nondeterministic,
                "flip_rate": round(nondeterministic / len(verdict_lists), 6) if verdict_lists else 0.0,
                "mean_binary_variance": round(sum(variances) / len(variances), 6) if variances else 0.0,
                "max_binary_variance": round(max(variances), 6) if variances else 0.0,
            }
        )
    if not summary:
        summary.append(
            {
                "guardrail": "none",
                "variants_with_repetitions": 0,
                "nondeterministic_variants": 0,
                "flip_rate": 0.0,
                "mean_binary_variance": 0.0,
                "max_binary_variance": 0.0,
            }
        )
    return summary


def stats_summary(
    msir_overall: list[dict[str, object]],
    nondeterminism: list[dict[str, object]],
    coverage: list[dict[str, object]],
    summary_dir: Path,
) -> list[dict[str, object]]:
    overall = msir_overall[0] if msir_overall else {}
    rows = [
        {
            "metric": "overall_msir_observed",
            "value": overall.get("mean", ""),
            "note": "Computed over observed seed-SMR variant sets.",
        },
        {
            "metric": "overall_msir_ci95_low",
            "value": overall.get("ci95_low", ""),
            "note": "Bootstrap CI over seed-SMR variant sets.",
        },
        {
            "metric": "overall_msir_ci95_high",
            "value": overall.get("ci95_high", ""),
            "note": "Bootstrap CI over seed-SMR variant sets.",
        },
    ]
    for row in nondeterminism:
        rows.append(
            {
                "metric": f"nondeterminism_flip_rate_{row['guardrail']}",
                "value": row["flip_rate"],
                "note": "Fraction of repeated variants with both allow and block verdicts.",
            }
        )
    for row in coverage:
        if int(row["missing_rows"]) > 0:
            rows.append(
                {
                    "metric": f"missing_rows_{row['guardrail']}",
                    "value": row["missing_rows"],
                    "note": "External quota or incomplete execution; metrics use observed rows only.",
                }
            )
    mcnemar = load_mcnemar_summary(summary_dir)
    if mcnemar:
        rows.append(
            {
                "metric": "mcnemar_status",
                "value": "computed",
                "note": f"Computed from seed-baseline verdicts in {summary_dir / 'mcnemar_summary.csv'}.",
            }
        )
        for item in mcnemar:
            rows.append(
                {
                    "metric": f"mcnemar_exact_p_{item.get('guardrail', '')}",
                    "value": item.get("mcnemar_exact_p", ""),
                    "note": (
                        f"paired_variants={item.get('paired_variants', '')}; "
                        f"discordant_pairs={item.get('discordant_pairs', '')}"
                    ),
                }
            )
    else:
        rows.append(
            {
                "metric": "mcnemar_status",
                "value": "not_computed",
                "note": "Original seed baseline verdicts are not present in Phase 5 raw results.",
            }
        )
    manual = load_manual_agreement_summary()
    if manual.get("manual_cohen_kappa"):
        rows.extend(
            [
                {
                    "metric": "manual_labeled_rows",
                    "value": manual.get("manual_labeled_rows", ""),
                    "note": "Rows in smr-paper/tables/manual_variant_spotcheck.csv with human_valid labels.",
                },
                {
                    "metric": "manual_raw_agreement",
                    "value": manual.get("manual_raw_agreement", ""),
                    "note": "Agreement between validator decision and human_valid labels.",
                },
                {
                    "metric": "manual_cohen_kappa",
                    "value": manual.get("manual_cohen_kappa", ""),
                    "note": "Cohen's kappa for validator-vs-human labels.",
                },
                {
                    "metric": "manual_kappa_status",
                    "value": "computed",
                    "note": "Computed in smr-paper/tables/manual_agreement_summary.csv.",
                },
            ]
        )
    else:
        rows.append(
            {
                "metric": "manual_kappa_status",
                "value": "human_labels_not_available",
                "note": "Populate human_valid in smr-paper/tables/manual_variant_spotcheck.csv and run compute_manual_agreement.py.",
            }
        )
    return rows


def write_table_pair(
    name: str,
    rows: list[dict[str, object]],
    fields: list[str],
    output_dir: Path,
    paper_dir: Path | None,
) -> None:
    write_csv(output_dir / name, rows, fields)
    if paper_dir is not None:
        write_csv(paper_dir / name, rows, fields)


def parse_args() -> argparse.Namespace:
    parser = argparse.ArgumentParser(description="Compute Phase 6 SMR metrics.")
    parser.add_argument("--input", type=Path, default=RAW_RESULTS_DIR / "results.jsonl")
    parser.add_argument("--variants", type=Path, default=VARIANT_DIR / "variants.jsonl")
    parser.add_argument("--expected-from-results", action="store_true")
    parser.add_argument("--output-dir", type=Path, default=RESULTS_DIR / "tables")
    parser.add_argument("--paper-dir", type=Path, default=PAPER_DIR / "tables")
    parser.add_argument("--skip-paper-copy", action="store_true")
    parser.add_argument("--bootstrap-iterations", type=int, default=2000)
    parser.add_argument("--random-seed", type=int, default=RANDOM_SEED)
    return parser.parse_args()


def main() -> None:
    args = parse_args()
    raw_rows, duplicates_removed = dedupe_results(load_jsonl(args.input))
    variants = None if args.expected_from_results else load_jsonl(args.variants)
    metadata = variant_metadata(variants, raw_rows)
    expected_counts = expected_variant_counts(metadata)
    outcomes = collapse_variant_outcomes(raw_rows, metadata)
    group_rows = build_group_metrics(outcomes, expected_counts)

    coverage = coverage_summary(raw_rows, metadata, duplicates_removed)
    msir_overall = summarize_indicator(
        group_rows,
        [],
        "inconsistent_int",
        "msir",
        args.bootstrap_iterations,
        args.random_seed,
    )
    msir_by_guardrail = summarize_indicator(
        group_rows,
        ["guardrail"],
        "inconsistent_int",
        "msir",
        args.bootstrap_iterations,
        args.random_seed,
    )
    msir_by_smr = summarize_indicator(
        group_rows,
        ["smr"],
        "inconsistent_int",
        "msir",
        args.bootstrap_iterations,
        args.random_seed,
    )
    msir_by_owasp = summarize_indicator(
        group_rows,
        ["owasp_category"],
        "inconsistent_int",
        "msir",
        args.bootstrap_iterations,
        args.random_seed,
    )
    msir_by_guardrail_smr = summarize_indicator(
        group_rows,
        ["guardrail", "smr"],
        "inconsistent_int",
        "msir",
        args.bootstrap_iterations,
        args.random_seed,
    )
    defense_gap_summary = summarize_indicator(
        group_rows,
        ["guardrail", "smr"],
        "defense_gap",
        "defense_gap",
        args.bootstrap_iterations,
        args.random_seed,
    )
    nondeterminism = nondeterminism_summary(raw_rows)
    flat_detection = flat_detection_summary(outcomes, ["guardrail", "smr"])
    paper_dir = None if args.skip_paper_copy else args.paper_dir
    stats = stats_summary(msir_overall, nondeterminism, coverage, paper_dir or args.output_dir)
    common_msir_fields = [
        "summary",
        "scope",
        "guardrail",
        "smr",
        "owasp_category",
        "n_seed_smr_sets",
        "inconsistent_sets",
        "mean",
        "ci95_low",
        "ci95_high",
        "complete_sets",
        "incomplete_sets",
        "observed_variants",
        "expected_variants",
    ]
    write_table_pair(
        "coverage_summary.csv",
        coverage,
        [
            "guardrail",
            "expected_variants",
            "observed_variants",
            "expected_repetitions",
            "expected_rows",
            "observed_rows",
            "missing_rows",
            "row_coverage_rate",
            "complete_variants",
            "duplicates_removed",
        ],
        args.output_dir,
        paper_dir,
    )
    write_table_pair("msir_overall.csv", msir_overall, common_msir_fields, args.output_dir, paper_dir)
    write_table_pair("msir_by_guardrail.csv", msir_by_guardrail, common_msir_fields, args.output_dir, paper_dir)
    write_table_pair("msir_by_smr.csv", msir_by_smr, common_msir_fields, args.output_dir, paper_dir)
    write_table_pair("msir_by_owasp.csv", msir_by_owasp, common_msir_fields, args.output_dir, paper_dir)
    write_table_pair(
        "msir_by_guardrail_smr.csv",
        msir_by_guardrail_smr,
        common_msir_fields,
        args.output_dir,
        paper_dir,
    )
    write_table_pair(
        "defense_gap_by_seed.csv",
        group_rows,
        [
            "guardrail",
            "seed_id",
            "smr",
            "relation_type",
            "owasp_category",
            "variants_observed",
            "variants_expected",
            "coverage_rate",
            "complete_set",
            "inconsistent",
            "blocked_variants",
            "allowed_variants",
            "block_rate_min",
            "block_rate_max",
            "defense_gap",
        ],
        args.output_dir,
        paper_dir,
    )
    write_table_pair(
        "defense_gap_summary.csv",
        defense_gap_summary,
        common_msir_fields,
        args.output_dir,
        paper_dir,
    )
    write_table_pair(
        "nondeterminism_summary.csv",
        nondeterminism,
        [
            "guardrail",
            "variants_with_repetitions",
            "nondeterministic_variants",
            "flip_rate",
            "mean_binary_variance",
            "max_binary_variance",
        ],
        args.output_dir,
        paper_dir,
    )
    write_table_pair(
        "flat_detection_summary.csv",
        flat_detection,
        [
            "guardrail",
            "smr",
            "variant_outcomes",
            "blocked_outcomes",
            "flat_block_rate",
            "mean_repetition_block_rate",
        ],
        args.output_dir,
        paper_dir,
    )
    write_table_pair(
        "stats_summary.csv",
        stats,
        ["metric", "value", "note"],
        args.output_dir,
        paper_dir,
    )

    summary = {
        "input": str(args.input),
        "rows_loaded": len(raw_rows) + duplicates_removed,
        "rows_after_dedupe": len(raw_rows),
        "duplicates_removed": duplicates_removed,
        "variant_outcomes": len(outcomes),
        "seed_smr_guardrail_sets": len(group_rows),
        "overall_msir": msir_overall[0]["mean"] if msir_overall else None,
        "paper_tables": None if paper_dir is None else str(paper_dir),
        "result_tables": str(args.output_dir),
    }
    print(json.dumps(summary, ensure_ascii=True, indent=2))


if __name__ == "__main__":
    main()
