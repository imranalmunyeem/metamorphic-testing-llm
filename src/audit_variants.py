"""Audit and optionally de-duplicate generated variant JSONL files."""

from __future__ import annotations

import argparse
import json
import sys
from collections import Counter
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

from config import VARIANT_DIR


def load_jsonl(path: Path) -> list[dict[str, object]]:
    if not path.exists():
        return []
    return [json.loads(line) for line in path.read_text(encoding="utf-8").splitlines() if line.strip()]


def write_jsonl(path: Path, rows: list[dict[str, object]]) -> None:
    with path.open("w", encoding="utf-8", newline="\n") as handle:
        for row in rows:
            handle.write(json.dumps(row, ensure_ascii=True) + "\n")


def audit(variants: list[dict[str, object]], rejects: list[dict[str, object]]) -> dict[str, object]:
    ids = [str(row.get("variant_id")) for row in variants]
    duplicate_ids = sorted(variant_id for variant_id, count in Counter(ids).items() if count > 1)
    attempts = Counter()
    for row in variants + rejects:
        if "seed_id" in row and "smr" in row:
            attempts[(str(row["seed_id"]), str(row["smr"]))] += 1
    short_sets = [
        {"seed_id": seed_id, "smr": smr, "attempted": count, "target": 8}
        for (seed_id, smr), count in sorted(attempts.items())
        if smr in {"SMR-1", "SMR-2", "SMR-3", "SMR-4"} and count < 8
    ]
    return {
        "accepted_total": len(variants),
        "rejects_total": len(rejects),
        "unique_variant_ids": len(set(ids)),
        "duplicate_id_count": len(ids) - len(set(ids)),
        "duplicate_ids": duplicate_ids[:100],
        "accepted_by_smr": dict(sorted(Counter(str(row.get("smr")) for row in variants).items())),
        "rejects_by_smr": dict(sorted(Counter(str(row.get("smr")) for row in rejects).items())),
        "short_seed_smr_sets": short_sets,
        "short_seed_smr_set_count": len(short_sets),
    }


def deduplicate(variants: list[dict[str, object]]) -> list[dict[str, object]]:
    seen: set[str] = set()
    deduped: list[dict[str, object]] = []
    for row in variants:
        variant_id = str(row.get("variant_id"))
        if variant_id in seen:
            continue
        seen.add(variant_id)
        deduped.append(row)
    return deduped


def prune_resolved_rejects(
    rejects: list[dict[str, object]],
    accepted_variant_ids: set[str],
) -> list[dict[str, object]]:
    pruned: list[dict[str, object]] = []
    for row in rejects:
        variant_id = row.get("variant_id")
        if variant_id is not None and str(variant_id) in accepted_variant_ids:
            continue
        pruned.append(row)
    return pruned


def parse_args() -> argparse.Namespace:
    parser = argparse.ArgumentParser(description="Audit generated SMR variants.")
    parser.add_argument("--variants", type=Path, default=VARIANT_DIR / "variants.jsonl")
    parser.add_argument("--rejects", type=Path, default=VARIANT_DIR / "rejects.jsonl")
    parser.add_argument("--summary", type=Path, default=VARIANT_DIR / "variant_audit.json")
    parser.add_argument("--dedupe", action="store_true")
    return parser.parse_args()


def main() -> None:
    args = parse_args()
    variants = load_jsonl(args.variants)
    rejects = load_jsonl(args.rejects)
    if args.dedupe:
        variants = deduplicate(variants)
        write_jsonl(args.variants, variants)
        rejects = prune_resolved_rejects(
            rejects,
            {str(row.get("variant_id")) for row in variants if row.get("variant_id") is not None},
        )
        write_jsonl(args.rejects, rejects)
    summary = audit(variants, rejects)
    args.summary.parent.mkdir(parents=True, exist_ok=True)
    args.summary.write_text(json.dumps(summary, ensure_ascii=True, indent=2) + "\n", encoding="utf-8")
    print(json.dumps(summary, ensure_ascii=True, indent=2))


if __name__ == "__main__":
    main()
