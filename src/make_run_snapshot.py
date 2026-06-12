"""Freeze a citation-ready run snapshot for the paper appendix."""

from __future__ import annotations

import argparse
import csv
import hashlib
import json
import subprocess
import sys
from datetime import datetime, timezone
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

from config import (  # noqa: E402
    BASE_DIR,
    DATA_DIR,
    LLM_REPETITIONS,
    MAX_RUN_USD,
    OPENAI_GENERATION_MODEL,
    OPENAI_JUDGE_MODEL,
    OPENAI_MODERATION_MODEL,
    PAPER_DIR,
    PROTECTAI_MODEL,
    RANDOM_SEED,
    RAW_RESULTS_DIR,
    RESULTS_DIR,
    VARIANT_DIR,
)


def sha256_file(path: Path) -> str | None:
    if not path.exists():
        return None
    digest = hashlib.sha256()
    with path.open("rb") as handle:
        for chunk in iter(lambda: handle.read(1024 * 1024), b""):
            digest.update(chunk)
    return digest.hexdigest()


def json_load(path: Path) -> dict[str, object] | None:
    if not path.exists():
        return None
    return json.loads(path.read_text(encoding="utf-8"))


def read_single_csv(path: Path) -> dict[str, str] | None:
    if not path.exists():
        return None
    with path.open("r", encoding="utf-8", newline="") as handle:
        rows = list(csv.DictReader(handle))
    return rows[0] if rows else None


def read_csv_rows(path: Path) -> list[dict[str, str]]:
    if not path.exists():
        return []
    with path.open("r", encoding="utf-8", newline="") as handle:
        return list(csv.DictReader(handle))


def count_jsonl(path: Path) -> int | None:
    if not path.exists():
        return None
    return sum(1 for line in path.read_text(encoding="utf-8").splitlines() if line.strip())


def git_text(args: list[str]) -> str:
    try:
        completed = subprocess.run(
            ["git", *args],
            cwd=BASE_DIR,
            check=True,
            text=True,
            capture_output=True,
        )
        return completed.stdout.strip()
    except Exception:
        return ""


def git_status() -> dict[str, object]:
    return {
        "head": git_text(["rev-parse", "HEAD"]),
        "branch": git_text(["branch", "--show-current"]),
        "status_short": git_text(["status", "--short"]).splitlines(),
        "remote": git_text(["remote", "-v"]).splitlines(),
    }


def file_inventory() -> dict[str, dict[str, object]]:
    paths = {
        "seeds": DATA_DIR / "seeds" / "seeds.jsonl",
        "variants": VARIANT_DIR / "variants.jsonl",
        "variants_canonicalized": VARIANT_DIR / "variants_canonicalized.jsonl",
        "raw_results": RAW_RESULTS_DIR / "results.jsonl",
        "raw_results_mitigated": RAW_RESULTS_DIR / "results_mitigated.jsonl",
        "baseline_metrics": RESULTS_DIR / "tables" / "msir_overall.csv",
        "mitigated_metrics": RESULTS_DIR / "tables_mitigated" / "msir_overall.csv",
    }
    inventory: dict[str, dict[str, object]] = {}
    for name, path in paths.items():
        inventory[name] = {
            "path": str(path),
            "exists": path.exists(),
            "bytes": path.stat().st_size if path.exists() else 0,
            "sha256": sha256_file(path),
            "jsonl_rows": count_jsonl(path) if path.suffix == ".jsonl" else None,
        }
    return inventory


def build_snapshot() -> dict[str, object]:
    baseline_overall = read_single_csv(RESULTS_DIR / "tables" / "msir_overall.csv")
    mitigated_overall = read_single_csv(RESULTS_DIR / "tables_mitigated" / "msir_overall.csv")
    mitigation = read_csv_rows(PAPER_DIR / "tables" / "mitigation.csv")
    baseline_coverage = read_csv_rows(RESULTS_DIR / "tables" / "coverage_summary.csv")
    mitigated_coverage = read_csv_rows(RESULTS_DIR / "tables_mitigated" / "coverage_summary.csv")
    return {
        "snapshot_created_utc": datetime.now(timezone.utc).isoformat(),
        "project_root": str(BASE_DIR),
        "paper_dir": str(PAPER_DIR),
        "config": {
            "openai_generation_model": OPENAI_GENERATION_MODEL,
            "openai_judge_model": OPENAI_JUDGE_MODEL,
            "openai_moderation_model": OPENAI_MODERATION_MODEL,
            "protectai_model": PROTECTAI_MODEL,
            "llm_repetitions": LLM_REPETITIONS,
            "random_seed": RANDOM_SEED,
            "max_run_usd": MAX_RUN_USD,
        },
        "headline": {
            "baseline_overall_msir": baseline_overall,
            "mitigated_overall_msir": mitigated_overall,
            "mitigation_by_guardrail": mitigation,
        },
        "coverage": {
            "baseline": baseline_coverage,
            "mitigated": mitigated_coverage,
        },
        "runner_summaries": {
            "baseline": json_load(RAW_RESULTS_DIR / "runner_summary.json"),
            "mitigated": json_load(RAW_RESULTS_DIR / "runner_mitigated_summary.json"),
            "canonicalization": json_load(VARIANT_DIR / "canonicalization_summary.json"),
        },
        "file_inventory": file_inventory(),
        "git": git_status(),
    }


def parse_args() -> argparse.Namespace:
    parser = argparse.ArgumentParser(description="Write the paper run snapshot.")
    parser.add_argument("--output", type=Path, default=PAPER_DIR / "snapshots" / "run_snapshot.json")
    return parser.parse_args()


def main() -> None:
    args = parse_args()
    snapshot = build_snapshot()
    args.output.parent.mkdir(parents=True, exist_ok=True)
    args.output.write_text(json.dumps(snapshot, ensure_ascii=True, indent=2) + "\n", encoding="utf-8")
    print(json.dumps({"snapshot": str(args.output), "bytes": args.output.stat().st_size}, indent=2))


if __name__ == "__main__":
    main()
