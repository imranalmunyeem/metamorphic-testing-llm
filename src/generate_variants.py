"""Generate and validate Phase 2 SMR variants."""

from __future__ import annotations

import argparse
import json
import os
import sys
import time
from collections import Counter
from concurrent.futures import ThreadPoolExecutor, as_completed
from pathlib import Path
from threading import Lock
from typing import Iterable

from dotenv import load_dotenv
from json_repair import repair_json
from openai import OpenAI
from tenacity import retry, stop_after_attempt, wait_exponential_jitter

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

from config import (  # noqa: E402
    DEFAULT_CONCURRENCY,
    MAX_RUN_USD,
    OPENAI_GENERATION_MODEL,
    OPENAI_JUDGE_MODEL,
    SEED_DIR,
    VARIANT_DIR,
)
from transforms import (  # noqa: E402
    INVARIANCE_SMRS,
    SMR2_LANGUAGES,
    VariantDraft,
    access_control_variants,
    build_paraphrase_prompt,
    build_translation_prompt,
    compact,
    composition_variants,
    encoding_variants,
    formatting_variants,
    make_variant_id,
    output_sanitization_variants,
)
from validate import (  # noqa: E402
    build_validation_prompt,
    deterministic_validation,
    parse_validation_response,
)


PRICE_INPUT_PER_MTOK = float(os.getenv("OPENAI_INPUT_PRICE_PER_MTOK", "1.50"))
PRICE_OUTPUT_PER_MTOK = float(os.getenv("OPENAI_OUTPUT_PRICE_PER_MTOK", "9.00"))


class UsageTracker:
    def __init__(self) -> None:
        self.lock = Lock()
        self.input_tokens = 0
        self.output_tokens = 0
        self.calls = 0

    def add(self, usage: object) -> None:
        if usage is None:
            return
        input_tokens = int(getattr(usage, "input_tokens", 0) or 0)
        output_tokens = int(getattr(usage, "output_tokens", 0) or 0)
        with self.lock:
            self.calls += 1
            self.input_tokens += input_tokens
            self.output_tokens += output_tokens

    def snapshot(self) -> dict[str, object]:
        with self.lock:
            cost = estimate_cost(self.input_tokens, self.output_tokens)
            return {
                "api_calls": self.calls,
                "input_tokens": self.input_tokens,
                "output_tokens": self.output_tokens,
                "estimated_cost_usd": round(cost, 6),
            }


def estimate_cost(input_tokens: int, output_tokens: int) -> float:
    return (
        (input_tokens / 1_000_000) * PRICE_INPUT_PER_MTOK
        + (output_tokens / 1_000_000) * PRICE_OUTPUT_PER_MTOK
    )


@retry(wait=wait_exponential_jitter(initial=1, max=30), stop=stop_after_attempt(5))
def call_openai(client: OpenAI, model: str, prompt: str, max_output_tokens: int) -> tuple[str, object]:
    response = client.responses.create(
        model=model,
        input=prompt,
        max_output_tokens=max_output_tokens,
    )
    return response.output_text.strip(), getattr(response, "usage", None)


def parse_generation_response(raw_text: str, expected_count: int) -> list[dict[str, str]]:
    repaired = repair_json(extract_json(raw_text), return_objects=True)
    variants = repaired.get("variants", []) if isinstance(repaired, dict) else []
    cleaned: list[dict[str, str]] = []
    seen: set[str] = set()
    for item in variants:
        if not isinstance(item, dict):
            continue
        text = compact(item.get("text", ""))
        if not text or text.casefold() in seen:
            continue
        seen.add(text.casefold())
        cleaned.append({k: str(v) for k, v in item.items() if k != "text"} | {"text": text})
        if len(cleaned) >= expected_count:
            break
    return cleaned


def extract_json(raw_text: str) -> str:
    raw_text = raw_text.strip()
    if raw_text.startswith("```"):
        raw_text = raw_text.removeprefix("```json").removeprefix("```").strip()
        raw_text = raw_text.removesuffix("```").strip()
    start = raw_text.find("{")
    end = raw_text.rfind("}")
    if start >= 0 and end > start:
        return raw_text[start : end + 1]
    return raw_text


def load_jsonl(path: Path) -> list[dict[str, object]]:
    if not path.exists():
        return []
    return [json.loads(line) for line in path.read_text(encoding="utf-8").splitlines() if line.strip()]


def append_jsonl(path: Path, rows: Iterable[dict[str, object]], lock: Lock) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    with lock:
        with path.open("a", encoding="utf-8", newline="\n") as handle:
            for row in rows:
                handle.write(json.dumps(row, ensure_ascii=True) + "\n")


def write_json(path: Path, payload: dict[str, object]) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(json.dumps(payload, ensure_ascii=True, indent=2) + "\n", encoding="utf-8")


def load_seeds(path: Path, limit_invariance: int | None) -> tuple[list[dict[str, str]], list[dict[str, str]], list[dict[str, str]]]:
    seeds = [json.loads(line) for line in path.read_text(encoding="utf-8").splitlines() if line.strip()]
    invariance = [seed for seed in seeds if seed["attack_type"] in {"prompt_injection", "jailbreak"}]
    if limit_invariance is not None:
        invariance = invariance[:limit_invariance]
    smr5 = [seed for seed in seeds if seed["attack_type"] == "access_control"]
    smr6 = [seed for seed in seeds if seed["attack_type"] == "composition_escalation"]
    return invariance, smr5, smr6


def existing_counts(path: Path, rejects_path: Path) -> tuple[set[str], Counter[tuple[str, str]]]:
    rows = load_jsonl(path)
    rejected_rows = load_jsonl(rejects_path)
    ids = {str(row["variant_id"]) for row in rows}
    counts: Counter[tuple[str, str]] = Counter()
    for row in rows + rejected_rows:
        if "seed_id" not in row or "smr" not in row:
            continue
        counts[(str(row["seed_id"]), str(row["smr"]))] += 1
    return ids, counts


def generated_variants_from_openai(
    client: OpenAI,
    usage: UsageTracker,
    seed: dict[str, str],
    smr: str,
    count: int,
) -> list[VariantDraft]:
    if smr == "SMR-1":
        prompt = build_paraphrase_prompt(seed["text"], count)
        raw, call_usage = call_openai(client, OPENAI_GENERATION_MODEL, prompt, max_output_tokens=2200)
        usage.add(call_usage)
        items = parse_generation_response(raw, count)
        return [
            VariantDraft(
                variant_id=make_variant_id(seed["id"], smr, index),
                seed_id=seed["id"],
                smr=smr,
                relation_type="invariance",
                transformation=f"paraphrase_{index:02d}",
                text=item["text"],
                variant_index=index,
                owasp_category=seed["owasp_category"],
                source=f"llm:{OPENAI_GENERATION_MODEL}",
            )
            for index, item in enumerate(items, start=1)
        ]

    if smr == "SMR-2":
        prompt = build_translation_prompt(seed["text"])
        raw, call_usage = call_openai(client, OPENAI_GENERATION_MODEL, prompt, max_output_tokens=3600)
        usage.add(call_usage)
        items = parse_generation_response(raw, count)
        drafts: list[VariantDraft] = []
        for index, item in enumerate(items, start=1):
            language = item.get("language") or SMR2_LANGUAGES[index - 1]
            drafts.append(
                VariantDraft(
                    variant_id=make_variant_id(seed["id"], smr, index),
                    seed_id=seed["id"],
                    smr=smr,
                    relation_type="invariance",
                    transformation=f"translation_{language}",
                    text=item["text"],
                    variant_index=index,
                    owasp_category=seed["owasp_category"],
                    source=f"llm:{OPENAI_GENERATION_MODEL}",
                    metadata={"language": language},
                )
            )
        return drafts

    raise ValueError(f"Unsupported OpenAI generation SMR: {smr}")


def deterministic_invariance_variants(seed: dict[str, str], smr: str, count: int) -> list[VariantDraft]:
    if smr == "SMR-3":
        return encoding_variants(seed, count=count)
    if smr == "SMR-4":
        return formatting_variants(seed, count=count)
    raise ValueError(f"Unsupported deterministic SMR: {smr}")


def validate_with_llm(
    client: OpenAI,
    usage: UsageTracker,
    seed: dict[str, str],
    smr: str,
    drafts: list[VariantDraft],
) -> dict[str, object]:
    prompt = build_validation_prompt(seed["text"], smr, drafts)
    raw, call_usage = call_openai(client, OPENAI_JUDGE_MODEL, prompt, max_output_tokens=1800)
    usage.add(call_usage)
    return {
        variant_id: result.to_record()
        for variant_id, result in parse_validation_response(
            raw,
            [draft.variant_id for draft in drafts],
            model=OPENAI_JUDGE_MODEL,
        ).items()
    }


def process_invariance_seed(
    seed: dict[str, str],
    variant_count: int,
    existing_ids: set[str],
    existing_by_seed_smr: Counter[tuple[str, str]],
    client: OpenAI,
    usage: UsageTracker,
) -> tuple[list[dict[str, object]], list[dict[str, object]], Counter[str]]:
    accepted: list[dict[str, object]] = []
    rejected: list[dict[str, object]] = []
    stats: Counter[str] = Counter()

    for smr in INVARIANCE_SMRS:
        if existing_by_seed_smr[(seed["id"], smr)] >= variant_count:
            stats[f"{smr}_skipped"] += 1
            continue
        start = time.perf_counter()
        if smr in {"SMR-1", "SMR-2"}:
            drafts = generated_variants_from_openai(client, usage, seed, smr, variant_count)
        else:
            drafts = deterministic_invariance_variants(seed, smr, variant_count)

        if len(drafts) < variant_count:
            rejected.append(
                {
                    "seed_id": seed["id"],
                    "smr": smr,
                    "reason": "generated_fewer_than_target",
                    "generated_count": len(drafts),
                    "target_count": variant_count,
                    "source": "generation",
                    "timestamp_unix": time.time(),
                }
            )
            stats[f"{smr}_generation_shortfall"] += variant_count - len(drafts)

        drafts = [draft for draft in drafts if draft.variant_id not in existing_ids]
        if not drafts:
            stats[f"{smr}_existing_ids_skipped"] += 1
            continue

        validations = validate_with_llm(client, usage, seed, smr, drafts)
        for draft in drafts:
            validation = validations[draft.variant_id]
            record = draft.to_record()
            record["validation"] = validation
            record["generated_at_unix"] = time.time()
            if validation["intent_preserved"]:
                accepted.append(record)
                stats[f"{smr}_accepted"] += 1
            else:
                rejected.append(record)
                stats[f"{smr}_rejected"] += 1
        stats[f"{smr}_seconds"] += round(time.perf_counter() - start, 3)

    return accepted, rejected, stats


def deterministic_relation_records(
    smr5_seeds: list[dict[str, str]],
    smr6_seeds: list[dict[str, str]],
    existing_ids: set[str],
) -> list[dict[str, object]]:
    drafts: list[VariantDraft] = []
    for seed in smr5_seeds:
        drafts.extend(access_control_variants(seed))
    for seed in smr6_seeds:
        drafts.extend(composition_variants(seed))
    drafts.extend(output_sanitization_variants())
    validations = deterministic_validation(drafts)
    records: list[dict[str, object]] = []
    for draft in drafts:
        if draft.variant_id in existing_ids:
            continue
        record = draft.to_record()
        record["validation"] = validations[draft.variant_id].to_record()
        record["generated_at_unix"] = time.time()
        records.append(record)
    return records


def summarize_variants(path: Path, rejects_path: Path, usage: UsageTracker, started: float) -> dict[str, object]:
    rows = load_jsonl(path)
    rejects = load_jsonl(rejects_path)
    by_smr = Counter(str(row.get("smr")) for row in rows)
    accepted_by_smr = Counter(
        str(row.get("smr"))
        for row in rows
        if row.get("validation", {}).get("intent_preserved") is True
    )
    return {
        "output": str(path),
        "rejects_output": str(rejects_path),
        "variants_total": len(rows),
        "rejects_total": len(rejects),
        "variants_by_smr": dict(sorted(by_smr.items())),
        "accepted_by_smr": dict(sorted(accepted_by_smr.items())),
        "usage": usage.snapshot(),
        "pricing": {
            "input_usd_per_mtok": PRICE_INPUT_PER_MTOK,
            "output_usd_per_mtok": PRICE_OUTPUT_PER_MTOK,
        },
        "elapsed_seconds": round(time.perf_counter() - started, 3),
    }


def parse_args() -> argparse.Namespace:
    parser = argparse.ArgumentParser(description="Generate Phase 2 SMR variants.")
    parser.add_argument("--seeds", type=Path, default=SEED_DIR / "seeds.jsonl")
    parser.add_argument("--output", type=Path, default=VARIANT_DIR / "variants.jsonl")
    parser.add_argument("--rejects-output", type=Path, default=VARIANT_DIR / "rejects.jsonl")
    parser.add_argument("--summary-output", type=Path, default=VARIANT_DIR / "run_summary.json")
    parser.add_argument("--limit-invariance-seeds", type=int, default=None)
    parser.add_argument("--variant-count", type=int, default=8)
    parser.add_argument("--workers", type=int, default=DEFAULT_CONCURRENCY)
    parser.add_argument("--force", action="store_true")
    parser.add_argument("--skip-differential", action="store_true")
    return parser.parse_args()


def main() -> None:
    args = parse_args()
    started = time.perf_counter()
    load_dotenv(dotenv_path=Path(".env"))
    if not os.getenv("OPENAI_API_KEY"):
        raise SystemExit("OPENAI_API_KEY is required for Phase 2 generation and validation.")

    if args.force:
        for path in (args.output, args.rejects_output, args.summary_output):
            if path.exists():
                path.unlink()

    invariance, smr5, smr6 = load_seeds(args.seeds, args.limit_invariance_seeds)
    existing_ids, counts = existing_counts(args.output, args.rejects_output)
    write_lock = Lock()
    usage = UsageTracker()
    client = OpenAI()
    aggregate_stats: Counter[str] = Counter()

    with ThreadPoolExecutor(max_workers=max(1, args.workers)) as executor:
        futures = [
            executor.submit(
                process_invariance_seed,
                seed,
                args.variant_count,
                existing_ids,
                counts,
                client,
                usage,
            )
            for seed in invariance
        ]
        completed = 0
        for future in as_completed(futures):
            accepted, rejected, stats = future.result()
            append_jsonl(args.output, accepted, write_lock)
            append_jsonl(args.rejects_output, rejected, write_lock)
            aggregate_stats.update(stats)
            completed += 1
            if completed % 5 == 0 or completed == len(futures):
                print(f"invariance_seeds_completed={completed}/{len(futures)}")

    if not args.skip_differential:
        deterministic_records = deterministic_relation_records(smr5, smr6, existing_ids)
        append_jsonl(args.output, deterministic_records, write_lock)
        aggregate_stats["deterministic_relation_records"] += len(deterministic_records)

    summary = summarize_variants(args.output, args.rejects_output, usage, started)
    summary["run_parameters"] = {
        "limit_invariance_seeds": args.limit_invariance_seeds,
        "variant_count": args.variant_count,
        "workers": args.workers,
        "generation_model": OPENAI_GENERATION_MODEL,
        "judge_model": OPENAI_JUDGE_MODEL,
        "max_run_usd": MAX_RUN_USD,
    }
    summary["stats"] = dict(sorted(aggregate_stats.items()))
    write_json(args.summary_output, summary)

    print(json.dumps(summary, ensure_ascii=True, indent=2))


if __name__ == "__main__":
    main()
