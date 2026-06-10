"""Batched, resumable experiment runner for Phase 5."""

from __future__ import annotations

import argparse
import csv
import importlib
import json
import sys
import time
from collections import Counter
from concurrent.futures import ThreadPoolExecutor, as_completed
from dataclasses import dataclass
from pathlib import Path
from threading import Lock
from typing import Iterable

from tenacity import retry, stop_after_attempt, wait_exponential_jitter

sys.path.insert(0, str(Path(__file__).resolve().parent))
sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

from config import (  # noqa: E402
    DEFAULT_CONCURRENCY,
    LLM_REPETITIONS,
    MAX_RUN_USD,
    OPENAI_JUDGE_MODEL,
    PAPER_DIR,
    RAW_RESULTS_DIR,
    VARIANT_DIR,
)


GUARDRAIL_CLASSES = {
    "regex_baseline": ("guardrails.regex_baseline", "RegexBaselineGuardrail"),
    "openai_moderation": ("guardrails.openai_moderation", "OpenAIModerationGuardrail"),
    "protectai": ("guardrails.protectai", "ProtectAIGuardrail"),
    "llmguard": ("guardrails.llmguard", "LLMGuardGuardrail"),
    "llm_judge": ("guardrails.llm_judge", "LLMJudgeGuardrail"),
}

REPETITIONS = {
    "regex_baseline": 1,
    "openai_moderation": 1,
    "protectai": 1,
    "llmguard": 1,
    "llm_judge": LLM_REPETITIONS,
}

LOCAL_MODEL_GUARDRAILS = {"protectai", "llmguard"}
OPENAI_GUARDRAILS = {"openai_moderation", "llm_judge"}
PAID_GUARDRAILS = {"llm_judge"}

PRICE_INPUT_PER_MTOK = 1.50
PRICE_OUTPUT_PER_MTOK = 9.00


@dataclass(frozen=True)
class Task:
    variant: dict[str, object]
    guardrail: str
    repetition: int

    @property
    def key(self) -> tuple[str, str, int]:
        return (str(self.variant["variant_id"]), self.guardrail, self.repetition)


def load_guardrail(name: str):
    module_name, class_name = GUARDRAIL_CLASSES[name]
    module = importlib.import_module(module_name)
    return getattr(module, class_name)()


def load_jsonl(path: Path) -> list[dict[str, object]]:
    if not path.exists():
        return []
    return [json.loads(line) for line in path.read_text(encoding="utf-8").splitlines() if line.strip()]


def append_jsonl(path: Path, row: dict[str, object], lock: Lock) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    with lock:
        with path.open("a", encoding="utf-8", newline="\n") as handle:
            handle.write(json.dumps(row, ensure_ascii=True, default=str) + "\n")


def completed_keys(path: Path) -> set[tuple[str, str, int]]:
    keys: set[tuple[str, str, int]] = set()
    for row in load_jsonl(path):
        try:
            keys.add((str(row["variant_id"]), str(row["guardrail"]), int(row["repetition"])))
        except KeyError:
            continue
    return keys


def load_variants(path: Path, limit: int | None) -> list[dict[str, object]]:
    variants = load_jsonl(path)
    if limit is not None:
        variants = variants[:limit]
    return variants


def build_tasks(
    variants: list[dict[str, object]],
    guardrails: list[str],
    done: set[tuple[str, str, int]],
) -> list[Task]:
    tasks: list[Task] = []
    for variant in variants:
        for guardrail in guardrails:
            for repetition in range(1, REPETITIONS[guardrail] + 1):
                task = Task(variant=variant, guardrail=guardrail, repetition=repetition)
                if task.key not in done:
                    tasks.append(task)
    return tasks


@retry(wait=wait_exponential_jitter(initial=1, max=30), stop=stop_after_attempt(5))
def run_task(adapter, task: Task) -> dict[str, object]:
    started = time.perf_counter()
    result = adapter.verdict(str(task.variant["text"]))
    elapsed_ms = round((time.perf_counter() - started) * 1000, 3)
    return {
        "seed_id": task.variant.get("seed_id"),
        "smr": task.variant.get("smr"),
        "variant_id": task.variant.get("variant_id"),
        "transformation": task.variant.get("transformation"),
        "relation_type": task.variant.get("relation_type"),
        "guardrail": task.guardrail,
        "repetition": task.repetition,
        "blocked": result.blocked,
        "score": result.score,
        "latency_ms": result.latency_ms or elapsed_ms,
        "runner_elapsed_ms": elapsed_ms,
        "owasp_category": task.variant.get("owasp_category"),
        "raw": result.raw,
        "timestamp_unix": time.time(),
    }


def run_guardrail_tasks(
    guardrail: str,
    tasks: list[Task],
    output: Path,
    write_lock: Lock,
    max_workers: int,
    max_results_remaining: int | None,
) -> int:
    if not tasks:
        return 0

    adapter = load_guardrail(guardrail)
    completed = 0
    worker_count = 1 if guardrail in LOCAL_MODEL_GUARDRAILS else max_workers
    if max_results_remaining is not None:
        tasks = tasks[:max_results_remaining]

    with ThreadPoolExecutor(max_workers=max(1, worker_count)) as executor:
        futures = [executor.submit(run_task, adapter, task) for task in tasks]
        for future in as_completed(futures):
            row = future.result()
            append_jsonl(output, row, write_lock)
            completed += 1
            if completed % 50 == 0 or completed == len(futures):
                print(f"{guardrail}_completed={completed}/{len(futures)}")
    return completed


def estimate_paid_cost(variants: list[dict[str, object]]) -> dict[str, object]:
    paid_calls = len(variants) * REPETITIONS["llm_judge"]
    static_prompt_chars = 820
    input_chars = sum(len(str(variant.get("text", ""))) + static_prompt_chars for variant in variants)
    input_tokens = int(input_chars / 4) * REPETITIONS["llm_judge"]
    output_tokens = paid_calls * 90
    cost = (input_tokens / 1_000_000) * PRICE_INPUT_PER_MTOK + (output_tokens / 1_000_000) * PRICE_OUTPUT_PER_MTOK
    return {
        "paid_guardrail": "llm_judge",
        "model": OPENAI_JUDGE_MODEL,
        "paid_calls": paid_calls,
        "estimated_input_tokens": input_tokens,
        "estimated_output_tokens": output_tokens,
        "estimated_cost_usd": round(cost, 4),
        "max_run_usd": MAX_RUN_USD,
        "pricing_assumption": {
            "input_usd_per_mtok": PRICE_INPUT_PER_MTOK,
            "output_usd_per_mtok": PRICE_OUTPUT_PER_MTOK,
        },
    }


def summarize_results(results: list[dict[str, object]], started: float, output: Path) -> dict[str, object]:
    by_guardrail = Counter(str(row.get("guardrail")) for row in results)
    by_smr = Counter(str(row.get("smr")) for row in results)
    blocked_by_guardrail = Counter(
        str(row.get("guardrail")) for row in results if row.get("blocked") is True
    )
    latencies: dict[str, list[float]] = {}
    for row in results:
        latencies.setdefault(str(row.get("guardrail")), []).append(float(row.get("latency_ms", 0.0)))
    mean_latency = {
        guardrail: round(sum(values) / len(values), 3)
        for guardrail, values in sorted(latencies.items())
        if values
    }
    return {
        "results_output": str(output),
        "results_total": len(results),
        "by_guardrail": dict(sorted(by_guardrail.items())),
        "by_smr": dict(sorted(by_smr.items())),
        "blocked_by_guardrail": dict(sorted(blocked_by_guardrail.items())),
        "mean_latency_ms_by_guardrail": mean_latency,
        "elapsed_seconds": round(time.perf_counter() - started, 3),
        "completed_at_unix": time.time(),
    }


def write_summary(summary: dict[str, object], json_path: Path, csv_path: Path) -> None:
    json_path.parent.mkdir(parents=True, exist_ok=True)
    json_path.write_text(json.dumps(summary, ensure_ascii=True, indent=2) + "\n", encoding="utf-8")
    csv_path.parent.mkdir(parents=True, exist_ok=True)
    with csv_path.open("w", encoding="utf-8", newline="") as handle:
        writer = csv.writer(handle)
        writer.writerow(["metric", "value"])
        writer.writerow(["results_total", summary["results_total"]])
        writer.writerow(["elapsed_seconds", summary["elapsed_seconds"]])
        for guardrail, count in summary["by_guardrail"].items():
            writer.writerow([f"results_{guardrail}", count])
        for guardrail, count in summary["blocked_by_guardrail"].items():
            writer.writerow([f"blocked_{guardrail}", count])
        for guardrail, latency in summary["mean_latency_ms_by_guardrail"].items():
            writer.writerow([f"mean_latency_ms_{guardrail}", latency])


def parse_guardrails(values: list[str]) -> list[str]:
    if "all" in values:
        return list(GUARDRAIL_CLASSES)
    return values


def parse_args() -> argparse.Namespace:
    parser = argparse.ArgumentParser(description="Run guardrail experiments over generated variants.")
    parser.add_argument("--variants", type=Path, default=VARIANT_DIR / "variants.jsonl")
    parser.add_argument("--output", type=Path, default=RAW_RESULTS_DIR / "results.jsonl")
    parser.add_argument("--summary-output", type=Path, default=RAW_RESULTS_DIR / "runner_summary.json")
    parser.add_argument("--paper-summary", type=Path, default=PAPER_DIR / "snapshots" / "phase5_runner_summary.json")
    parser.add_argument("--paper-table", type=Path, default=PAPER_DIR / "tables" / "runner_summary.csv")
    parser.add_argument("--guardrails", nargs="+", default=["all"], choices=sorted(GUARDRAIL_CLASSES) + ["all"])
    parser.add_argument("--limit-variants", type=int, default=None)
    parser.add_argument("--max-results", type=int, default=None)
    parser.add_argument("--workers", type=int, default=DEFAULT_CONCURRENCY)
    parser.add_argument("--estimate-only", action="store_true")
    parser.add_argument("--force", action="store_true")
    return parser.parse_args()


def main() -> None:
    args = parse_args()
    started = time.perf_counter()
    guardrails = parse_guardrails(args.guardrails)
    variants = load_variants(args.variants, args.limit_variants)
    estimate = estimate_paid_cost(variants)
    print("cost_estimate=" + json.dumps(estimate, ensure_ascii=True))
    if args.estimate_only:
        return
    if estimate["estimated_cost_usd"] > MAX_RUN_USD:
        raise SystemExit(
            f"Estimated cost ${estimate['estimated_cost_usd']} exceeds MAX_RUN_USD=${MAX_RUN_USD}."
        )

    if args.force and args.output.exists():
        args.output.unlink()

    done = completed_keys(args.output)
    tasks = build_tasks(variants, guardrails, done)
    total_planned = len(tasks)
    print(f"variants={len(variants)} guardrails={guardrails} already_completed={len(done)} pending={total_planned}")
    write_lock = Lock()
    completed_this_run = 0

    for guardrail in guardrails:
        guardrail_tasks = [task for task in tasks if task.guardrail == guardrail]
        remaining = None if args.max_results is None else max(0, args.max_results - completed_this_run)
        if remaining == 0:
            break
        completed = run_guardrail_tasks(
            guardrail,
            guardrail_tasks,
            args.output,
            write_lock,
            max_workers=args.workers,
            max_results_remaining=remaining,
        )
        completed_this_run += completed
        if args.max_results is not None and completed_this_run >= args.max_results:
            print(f"max_results_reached={args.max_results}")
            break

    results = load_jsonl(args.output)
    summary = summarize_results(results, started, args.output)
    summary["cost_estimate"] = estimate
    summary["run_parameters"] = {
        "variant_count": len(variants),
        "guardrails": guardrails,
        "workers": args.workers,
        "max_results": args.max_results,
        "completed_this_run": completed_this_run,
        "pending_at_start": total_planned,
    }
    write_summary(summary, args.summary_output, args.paper_table)
    write_summary(summary, args.paper_summary, args.paper_table)
    print(json.dumps(summary, ensure_ascii=True, indent=2))


if __name__ == "__main__":
    main()
