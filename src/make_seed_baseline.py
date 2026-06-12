"""Create original-seed baseline inputs for paired significance tests."""

from __future__ import annotations

import argparse
import json
from pathlib import Path

import sys

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

from config import SEED_DIR, VARIANT_DIR  # noqa: E402


def load_jsonl(path: Path) -> list[dict[str, object]]:
    if not path.exists():
        return []
    return [json.loads(line) for line in path.read_text(encoding="utf-8").splitlines() if line.strip()]


def write_jsonl(path: Path, rows: list[dict[str, object]]) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    with path.open("w", encoding="utf-8", newline="\n") as handle:
        for row in rows:
            handle.write(json.dumps(row, ensure_ascii=True, default=str) + "\n")


def raw_smr7_text(text: str) -> str:
    prefix = "Echo the following user-supplied content as formatted HTML without executing it: "
    if text.startswith(prefix):
        return text
    return text


def build_seed_baselines(seeds: list[dict[str, object]], variants: list[dict[str, object]]) -> list[dict[str, object]]:
    seed_by_id = {str(row["id"]): row for row in seeds}
    variant_seed_ids = sorted({str(row["seed_id"]) for row in variants})
    rows: list[dict[str, object]] = []

    for seed_id in variant_seed_ids:
        seed = seed_by_id.get(seed_id)
        if seed is not None:
            rows.append(
                {
                    "variant_id": f"SEED::{seed_id}",
                    "seed_id": seed_id,
                    "smr": "SEED",
                    "relation_type": "seed_baseline",
                    "transformation": "original_seed",
                    "text": seed["text"],
                    "owasp_category": seed.get("owasp_category", ""),
                    "source": seed.get("source", "data/seeds/seeds.jsonl"),
                }
            )
            continue

        raw_variant = next(
            (
                row
                for row in variants
                if str(row.get("seed_id")) == seed_id and str(row.get("transformation", "")).endswith(":raw")
            ),
            None,
        )
        if raw_variant is None:
            raw_variant = next((row for row in variants if str(row.get("seed_id")) == seed_id), None)
        if raw_variant is None:
            continue
        rows.append(
            {
                "variant_id": f"SEED::{seed_id}",
                "seed_id": seed_id,
                "smr": "SEED",
                "relation_type": "seed_baseline",
                "transformation": "original_seed_or_raw_payload",
                "text": raw_smr7_text(str(raw_variant.get("text", ""))),
                "owasp_category": raw_variant.get("owasp_category", ""),
                "source": "derived_from_raw_variant",
            }
        )

    return rows


def parse_args() -> argparse.Namespace:
    parser = argparse.ArgumentParser(description="Create original seed-baseline rows for McNemar tests.")
    parser.add_argument("--seeds", type=Path, default=SEED_DIR / "seeds.jsonl")
    parser.add_argument("--variants", type=Path, default=VARIANT_DIR / "variants.jsonl")
    parser.add_argument("--output", type=Path, default=VARIANT_DIR / "seed_baseline.jsonl")
    return parser.parse_args()


def main() -> None:
    args = parse_args()
    rows = build_seed_baselines(load_jsonl(args.seeds), load_jsonl(args.variants))
    write_jsonl(args.output, rows)
    print(json.dumps({"output": str(args.output), "seed_baseline_rows": len(rows)}, indent=2))


if __name__ == "__main__":
    main()
