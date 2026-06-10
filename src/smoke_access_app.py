"""Smoke-test the SMR-5 access-control mini-app."""

from __future__ import annotations

import argparse
import csv
import json
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent))
sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

from access_app.app import answer_query, relation_holds  # noqa: E402
from config import PAPER_DIR  # noqa: E402


def load_scenarios(path: Path, limit: int | None) -> list[dict[str, object]]:
    rows = [json.loads(line) for line in path.read_text(encoding="utf-8").splitlines() if line.strip()]
    return rows[:limit] if limit is not None else rows


def run_scenarios(scenarios: list[dict[str, object]]) -> list[dict[str, object]]:
    rows: list[dict[str, object]] = []
    for scenario in scenarios:
        low = answer_query(str(scenario["query"]), str(scenario["low_role"]))
        high = answer_query(str(scenario["query"]), str(scenario["high_role"]))
        holds = relation_holds(low, high)
        for role_level, result in [("low", low), ("high", high)]:
            row = result.to_dict()
            row.update(
                {
                    "scenario_id": scenario["id"],
                    "role_level": role_level,
                    "relation_holds": holds,
                    "expected_sensitive_markers": "|".join(scenario.get("expected_sensitive_markers", [])),
                }
            )
            rows.append(row)
            print(
                json.dumps(
                    {
                        "scenario_id": scenario["id"],
                        "role_level": role_level,
                        "role": result.role,
                        "retrieved_doc_ids": result.retrieved_doc_ids,
                        "leaked_markers": result.leaked_markers,
                        "relation_holds": holds,
                    },
                    ensure_ascii=True,
                )
            )
    return rows


def write_csv(rows: list[dict[str, object]], path: Path) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    fieldnames = [
        "scenario_id",
        "role_level",
        "role",
        "role_clearance",
        "query",
        "retrieved_doc_ids",
        "retrieved_sensitivities",
        "leaked_markers",
        "relation_holds",
        "latency_ms",
        "expected_sensitive_markers",
        "answer",
    ]
    with path.open("w", encoding="utf-8", newline="") as handle:
        writer = csv.DictWriter(handle, fieldnames=fieldnames)
        writer.writeheader()
        for row in rows:
            cleaned = dict(row)
            for key in ["retrieved_doc_ids", "retrieved_sensitivities", "leaked_markers"]:
                cleaned[key] = "|".join(cleaned.get(key, []))
            writer.writerow({key: cleaned.get(key, "") for key in fieldnames})


def parse_args() -> argparse.Namespace:
    parser = argparse.ArgumentParser(description="Smoke-test SMR-5 mini-app.")
    parser.add_argument("--scenarios", type=Path, default=Path("data/access_scenarios/scenarios.jsonl"))
    parser.add_argument("--limit", type=int, default=3)
    parser.add_argument("--output", type=Path, default=PAPER_DIR / "tables" / "access_control_smoke.csv")
    return parser.parse_args()


def main() -> None:
    args = parse_args()
    rows = run_scenarios(load_scenarios(args.scenarios, args.limit))
    write_csv(rows, args.output)
    print(f"wrote_access_smoke={args.output}")


if __name__ == "__main__":
    main()
