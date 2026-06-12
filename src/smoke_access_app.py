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
from access_app.docs import DOCUMENTS  # noqa: E402
from config import PAPER_DIR  # noqa: E402


MARKERS_BY_DOC_ID = {
    doc.doc_id: list(doc.markers)
    for doc in DOCUMENTS
}


def load_scenarios(path: Path, limit: int | None) -> list[dict[str, object]]:
    rows = [json.loads(line) for line in path.read_text(encoding="utf-8").splitlines() if line.strip()]
    return rows[:limit] if limit is not None else rows


def run_scenarios(scenarios: list[dict[str, object]]) -> list[dict[str, object]]:
    rows: list[dict[str, object]] = []
    for scenario in scenarios:
        low = answer_query(str(scenario["query"]), str(scenario["low_role"]))
        high = answer_query(str(scenario["query"]), str(scenario["high_role"]))
        holds = relation_holds(low, high)
        expected_markers = [str(marker) for marker in scenario.get("expected_sensitive_markers", [])]
        for role_level, result in [("low", low), ("high", high)]:
            answer_lower = result.answer.casefold()
            observed_expected_markers = [
                marker for marker in expected_markers if marker.casefold() in answer_lower
            ]
            retrieved_markers = {
                marker
                for doc_id in result.retrieved_doc_ids
                for marker in MARKERS_BY_DOC_ID.get(doc_id, [])
            }
            retrieved_expected_markers = [
                marker for marker in expected_markers if marker in retrieved_markers
            ]
            row = result.to_dict()
            row.update(
                {
                    "scenario_id": scenario["id"],
                    "role_level": role_level,
                    "relation_holds": holds,
                    "expected_sensitive_markers": "|".join(expected_markers),
                    "expected_markers_in_answer": observed_expected_markers,
                    "expected_markers_in_retrieved_docs": retrieved_expected_markers,
                    "low_leaked_expected_marker": role_level == "low" and bool(observed_expected_markers),
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
        "expected_markers_in_answer",
        "expected_markers_in_retrieved_docs",
        "low_leaked_expected_marker",
        "latency_ms",
        "expected_sensitive_markers",
        "answer",
    ]
    with path.open("w", encoding="utf-8", newline="") as handle:
        writer = csv.DictWriter(handle, fieldnames=fieldnames)
        writer.writeheader()
        for row in rows:
            cleaned = dict(row)
            for key in [
                "retrieved_doc_ids",
                "retrieved_sensitivities",
                "leaked_markers",
                "expected_markers_in_answer",
                "expected_markers_in_retrieved_docs",
            ]:
                cleaned[key] = "|".join(cleaned.get(key, []))
            writer.writerow({key: cleaned.get(key, "") for key in fieldnames})


def write_summary_csv(rows: list[dict[str, object]], path: Path) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    low_rows = [row for row in rows if row["role_level"] == "low"]
    high_rows = [row for row in rows if row["role_level"] == "high"]
    scenario_ids = sorted({str(row["scenario_id"]) for row in rows})
    relation_failures = sorted(
        {
            str(row["scenario_id"])
            for row in rows
            if str(row.get("relation_holds")).lower() != "true"
        }
    )
    low_leak_failures = sorted(
        {
            str(row["scenario_id"])
            for row in low_rows
            if row.get("leaked_markers") or row.get("low_leaked_expected_marker")
        }
    )
    high_marker_answers = sum(1 for row in high_rows if row.get("expected_markers_in_answer"))
    high_marker_retrievals = sum(1 for row in high_rows if row.get("expected_markers_in_retrieved_docs"))
    high_marker_rate = high_marker_answers / len(high_rows) if high_rows else 0.0
    high_retrieval_rate = high_marker_retrievals / len(high_rows) if high_rows else 0.0
    summary_rows = [
        {"metric": "scenarios", "value": len(scenario_ids), "note": "Distinct SMR-5 role-pair scenarios."},
        {"metric": "rows", "value": len(rows), "note": "Low-role and high-role application calls."},
        {"metric": "relation_failures", "value": len(relation_failures), "note": "|".join(relation_failures)},
        {"metric": "low_role_leak_failures", "value": len(low_leak_failures), "note": "|".join(low_leak_failures)},
        {"metric": "high_role_expected_marker_retrievals", "value": high_marker_retrievals, "note": "High-role retrieval contexts containing at least one expected marker."},
        {"metric": "high_role_expected_marker_retrieval_rate", "value": round(high_retrieval_rate, 6), "note": "Diagnostic evidence that the high role could access the relevant sensitive document."},
        {"metric": "high_role_expected_marker_answers", "value": high_marker_answers, "note": "High-role answers containing at least one expected marker."},
        {"metric": "high_role_expected_marker_answer_rate", "value": round(high_marker_rate, 6), "note": "This is diagnostic, not required for the no-low-leak relation."},
    ]
    with path.open("w", encoding="utf-8", newline="") as handle:
        writer = csv.DictWriter(handle, fieldnames=["metric", "value", "note"])
        writer.writeheader()
        writer.writerows(summary_rows)


def parse_args() -> argparse.Namespace:
    parser = argparse.ArgumentParser(description="Smoke-test SMR-5 mini-app.")
    parser.add_argument("--scenarios", type=Path, default=Path("data/access_scenarios/scenarios.jsonl"))
    parser.add_argument("--limit", type=int, default=None)
    parser.add_argument("--output", type=Path, default=PAPER_DIR / "tables" / "access_control_smoke.csv")
    parser.add_argument("--summary-output", type=Path, default=PAPER_DIR / "tables" / "access_control_summary.csv")
    return parser.parse_args()


def main() -> None:
    args = parse_args()
    rows = run_scenarios(load_scenarios(args.scenarios, args.limit))
    write_csv(rows, args.output)
    write_summary_csv(rows, args.summary_output)
    print(f"wrote_access_smoke={args.output}")
    print(f"wrote_access_summary={args.summary_output}")


if __name__ == "__main__":
    main()
