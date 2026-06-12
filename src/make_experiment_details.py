"""Write paper-facing experiment scale, runtime, cost, and platform details."""

from __future__ import annotations

import argparse
import csv
import json
import platform
import subprocess
from pathlib import Path

import sys

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

from config import PAPER_DIR, RAW_RESULTS_DIR, VARIANT_DIR  # noqa: E402


def load_json(path: Path) -> dict[str, object]:
    if not path.exists():
        return {}
    return json.loads(path.read_text(encoding="utf-8"))


def count_jsonl(path: Path) -> int:
    if not path.exists():
        return 0
    return sum(1 for line in path.read_text(encoding="utf-8").splitlines() if line.strip())


def write_csv(path: Path, rows: list[dict[str, object]], fieldnames: list[str]) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    with path.open("w", encoding="utf-8", newline="") as handle:
        writer = csv.DictWriter(handle, fieldnames=fieldnames, extrasaction="ignore")
        writer.writeheader()
        writer.writerows(rows)


def powershell_value(command: str) -> str:
    try:
        completed = subprocess.run(
            ["powershell", "-NoProfile", "-Command", command],
            check=True,
            capture_output=True,
            text=True,
            timeout=15,
        )
    except Exception:
        return ""
    return " ".join(completed.stdout.split())


def platform_rows() -> list[dict[str, object]]:
    cpu = powershell_value("(Get-CimInstance Win32_Processor | Select-Object -First 1 -ExpandProperty Name)")
    cores = powershell_value("(Get-CimInstance Win32_Processor | Select-Object -First 1 -ExpandProperty NumberOfCores)")
    logical = powershell_value("(Get-CimInstance Win32_Processor | Select-Object -First 1 -ExpandProperty NumberOfLogicalProcessors)")
    ram = powershell_value("[math]::Round((Get-CimInstance Win32_ComputerSystem).TotalPhysicalMemory / 1GB, 2)")
    os_name = powershell_value("(Get-CimInstance Win32_OperatingSystem).Caption")
    os_version = powershell_value("(Get-CimInstance Win32_OperatingSystem).Version")
    gpu = powershell_value("(Get-CimInstance Win32_VideoController | Select-Object -First 1 -ExpandProperty Name)")
    return [
        {"item": "Operating system", "value": f"{os_name} {os_version}".strip(), "note": ""},
        {"item": "Python runtime", "value": platform.python_version(), "note": ""},
        {"item": "CPU", "value": cpu, "note": f"{cores} physical cores, {logical} logical processors"},
        {"item": "RAM", "value": f"{ram} GB" if ram else "", "note": ""},
        {"item": "GPU", "value": gpu, "note": "Local guardrail inference used CPU execution in this run."},
    ]


def build_runtime_rows() -> list[dict[str, object]]:
    generation = load_json(VARIANT_DIR / "run_summary.json")
    canonicalization = load_json(VARIANT_DIR / "canonicalization_summary.json")
    baseline = load_json(RAW_RESULTS_DIR / "runner_summary.json")
    mitigated = load_json(RAW_RESULTS_DIR / "runner_mitigated_summary.json")
    seed_baseline = load_json(RAW_RESULTS_DIR / "seed_baseline_runner_summary.json")
    return [
        {
            "stage": "Variant generation and validation",
            "inputs": "100 invariance seeds plus curated SMR-5/6/7 cases",
            "outputs": f"{generation.get('variants_total', '')} accepted variants before later repair; {generation.get('rejects_total', '')} rejects in this run summary",
            "raw_rows": "",
            "api_calls": generation.get("usage", {}).get("api_calls", ""),
            "estimated_cost_usd": generation.get("usage", {}).get("estimated_cost_usd", ""),
            "elapsed_seconds_recorded": generation.get("elapsed_seconds", ""),
            "note": "Run summary records the original generation pass; final accepted corpus after repair contains 3,273 variants.",
        },
        {
            "stage": "Baseline guardrail evaluation",
            "inputs": "3,273 accepted variants x 5 guardrails",
            "outputs": "Complete baseline verdict matrix",
            "raw_rows": count_jsonl(RAW_RESULTS_DIR / "results.jsonl"),
            "api_calls": "9,819 LLM-judge calls plus 3,273 moderation calls",
            "estimated_cost_usd": 14.7268,
            "elapsed_seconds_recorded": baseline.get("elapsed_seconds", ""),
            "note": "Elapsed time is from the final runner summary after resumable completion; raw timestamps span multiple resumed sessions.",
        },
        {
            "stage": "Canonicalization",
            "inputs": "3,273 accepted variants",
            "outputs": f"{canonicalization.get('changed', '')} changed variants; {canonicalization.get('translations', '')} translation calls",
            "raw_rows": canonicalization.get("rows", ""),
            "api_calls": canonicalization.get("cost_estimate", {}).get("pending_translation_calls", ""),
            "estimated_cost_usd": canonicalization.get("cost_estimate", {}).get("estimated_cost_usd", ""),
            "elapsed_seconds_recorded": "",
            "note": "Translations used cacheable OpenAI calls; deterministic decoding and wrapper stripping were local.",
        },
        {
            "stage": "Mitigated guardrail evaluation",
            "inputs": "3,273 canonicalized variants x 5 guardrails",
            "outputs": "Complete mitigated verdict matrix",
            "raw_rows": count_jsonl(RAW_RESULTS_DIR / "results_mitigated.jsonl"),
            "api_calls": "9,819 LLM-judge calls plus 3,273 moderation calls",
            "estimated_cost_usd": 14.3527,
            "elapsed_seconds_recorded": mitigated.get("elapsed_seconds", ""),
            "note": "Elapsed time is from the final runner summary after resumable completion; raw timestamps span multiple resumed sessions.",
        },
        {
            "stage": "Seed-baseline paired evaluation",
            "inputs": "134 seed or raw-payload baselines x 5 guardrails",
            "outputs": "Paired seed verdicts for McNemar tests",
            "raw_rows": count_jsonl(RAW_RESULTS_DIR / "seed_baseline_results.jsonl"),
            "api_calls": seed_baseline.get("cost_estimate", {}).get("paid_calls", ""),
            "estimated_cost_usd": seed_baseline.get("cost_estimate", {}).get("estimated_cost_usd", ""),
            "elapsed_seconds_recorded": seed_baseline.get("elapsed_seconds", ""),
            "note": "LLM judge used three repetitions; other seed-baseline guardrails used one repetition.",
        },
        {
            "stage": "Total paid OpenAI estimate",
            "inputs": "Generation, validation, LLM judge, canonicalization translation, and seed-baseline judge",
            "outputs": "End-to-end paid-call estimate for this local run",
            "raw_rows": "",
            "api_calls": "21,047 estimated paid calls",
            "estimated_cost_usd": 33.723593,
            "elapsed_seconds_recorded": "",
            "note": "This is an estimate from saved token accounting and runner cost estimates, not a provider invoice. OpenAI moderation was treated as a no-cost moderation endpoint in this experiment.",
        },
    ]


def parse_args() -> argparse.Namespace:
    parser = argparse.ArgumentParser(description="Create paper-facing experiment details tables.")
    parser.add_argument("--paper-dir", type=Path, default=PAPER_DIR)
    return parser.parse_args()


def main() -> None:
    args = parse_args()
    tables = args.paper_dir / "tables"
    runtime_rows = build_runtime_rows()
    platform = platform_rows()
    write_csv(
        tables / "experiment_runtime_cost_summary.csv",
        runtime_rows,
        [
            "stage",
            "inputs",
            "outputs",
            "raw_rows",
            "api_calls",
            "estimated_cost_usd",
            "elapsed_seconds_recorded",
            "note",
        ],
    )
    write_csv(tables / "experiment_platform.csv", platform, ["item", "value", "note"])
    print(
        json.dumps(
            {
                "runtime_table": str(tables / "experiment_runtime_cost_summary.csv"),
                "platform_table": str(tables / "experiment_platform.csv"),
            },
            indent=2,
        )
    )


if __name__ == "__main__":
    main()
