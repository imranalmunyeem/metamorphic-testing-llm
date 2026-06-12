"""Canonicalise generated SMR variants before mitigated guardrail runs."""

from __future__ import annotations

import argparse
import base64
import codecs
import hashlib
import html
import json
import re
import string
import sys
import time
import unicodedata
from pathlib import Path
from urllib.parse import unquote

from dotenv import load_dotenv
from langdetect import DetectorFactory, detect
from openai import OpenAI
from tenacity import retry, stop_after_attempt, wait_exponential_jitter

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

from config import (  # noqa: E402
    MAX_RUN_USD,
    OPENAI_GENERATION_MODEL,
    PAPER_DIR,
    SEED_DIR,
    VARIANT_DIR,
)


DetectorFactory.seed = 20260610

PRICE_INPUT_PER_MTOK = 1.50
PRICE_OUTPUT_PER_MTOK = 9.00

CYRILLIC_HOMOGLYPHS = {
    ord(chr(0x0410)): "A",
    ord(chr(0x0412)): "B",
    ord(chr(0x0415)): "E",
    ord(chr(0x041A)): "K",
    ord(chr(0x041C)): "M",
    ord(chr(0x041D)): "H",
    ord(chr(0x041E)): "O",
    ord(chr(0x0420)): "P",
    ord(chr(0x0421)): "C",
    ord(chr(0x0422)): "T",
    ord(chr(0x0425)): "X",
    ord(chr(0x0430)): "a",
    ord(chr(0x0435)): "e",
    ord(chr(0x043E)): "o",
    ord(chr(0x0440)): "p",
    ord(chr(0x0441)): "c",
    ord(chr(0x0445)): "x",
    ord(chr(0x0443)): "y",
    ord(chr(0x0456)): "i",
}

LEETSPEAK = str.maketrans(
    {
        "0": "o",
        "1": "i",
        "3": "e",
        "4": "a",
        "5": "s",
        "7": "t",
        "@": "a",
        "$": "s",
    }
)


def load_jsonl(path: Path) -> list[dict[str, object]]:
    if not path.exists():
        return []
    return [json.loads(line) for line in path.read_text(encoding="utf-8").splitlines() if line.strip()]


def write_jsonl(path: Path, rows: list[dict[str, object]]) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    with path.open("w", encoding="utf-8", newline="\n") as handle:
        for row in rows:
            handle.write(json.dumps(row, ensure_ascii=True) + "\n")


def append_jsonl(path: Path, row: dict[str, object]) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    with path.open("a", encoding="utf-8", newline="\n") as handle:
        handle.write(json.dumps(row, ensure_ascii=True) + "\n")


def load_seed_texts(path: Path) -> dict[str, str]:
    return {str(row["id"]): str(row["text"]) for row in load_jsonl(path)}


def load_translation_cache(path: Path) -> dict[str, str]:
    cache: dict[str, str] = {}
    for row in load_jsonl(path):
        variant_id = row.get("variant_id")
        translated = row.get("translated_text")
        if variant_id and translated:
            cache[str(variant_id)] = str(translated)
    return cache


def cache_key(text: str) -> str:
    return hashlib.sha256(text.encode("utf-8")).hexdigest()


def printable_ratio(text: str) -> float:
    if not text:
        return 0.0
    printable = set(string.printable)
    return sum(1 for char in text if char in printable or char.isspace()) / len(text)


def compact_spaces(text: str) -> str:
    return re.sub(r"\s+", " ", text).strip()


def strip_wrappers(text: str) -> tuple[str, list[str]]:
    actions: list[str] = []
    stripped = text.strip()

    code_match = re.fullmatch(r"```[A-Za-z0-9_-]*\s*(.*?)\s*```", stripped, flags=re.S)
    if code_match:
        stripped = code_match.group(1).strip()
        actions.append("strip_code_fence")

    if stripped.startswith("{") and stripped.endswith("}"):
        try:
            parsed = json.loads(stripped)
            if isinstance(parsed, dict):
                for key in ("user_message", "message", "content", "body", "text", "instruction"):
                    if key in parsed and isinstance(parsed[key], str):
                        stripped = parsed[key].strip()
                        actions.append("extract_json_message")
                        break
        except json.JSONDecodeError:
            pass

    yaml_match = re.search(r"(?im)^user_message:\s*\|\s*\n(?P<body>(?:\s+.+\n?)+)", stripped)
    if yaml_match:
        lines = [line.strip() for line in yaml_match.group("body").splitlines()]
        stripped = "\n".join(line for line in lines if line)
        actions.append("extract_yaml_message")

    xml_match = re.search(r"(?is)<body>(.*?)</body>", stripped)
    if xml_match:
        stripped = xml_match.group(1).strip()
        actions.append("extract_xml_body")
    elif re.search(r"(?is)<message>(.*?)</message>", stripped):
        stripped = re.sub(r"(?is)</?message>", "", stripped).strip()
        actions.append("strip_xml_message")

    marker_patterns = [
        r"(?is)Please process this message:\s*(.*?)\s*$",
        r"(?is)Customer note:\s*(.*?)\s*End of note\.?\s*$",
        r"(?is)Submit this text as the user:\s*(.*?)\s*$",
    ]
    for pattern in marker_patterns:
        match = re.search(pattern, stripped)
        if match:
            stripped = match.group(1).strip()
            actions.append("extract_wrapped_message")
            break

    if any(line.lstrip().startswith(">") for line in stripped.splitlines()):
        stripped = "\n".join(re.sub(r"^\s*>\s?", "", line) for line in stripped.splitlines())
        actions.append("strip_markdown_quote")

    return stripped.strip(), actions


def decode_base64_segments(text: str) -> tuple[str, list[str]]:
    actions: list[str] = []

    def replace(match: re.Match[str]) -> str:
        token = match.group(0)
        try:
            decoded = base64.b64decode(token, validate=True).decode("utf-8")
        except Exception:
            return token
        if len(decoded) < 4 or printable_ratio(decoded) < 0.85:
            return token
        actions.append("decode_base64")
        return decoded

    return re.sub(r"\b[A-Za-z0-9+/]{20,}={0,2}\b", replace, text), actions


def decode_hex_segments(text: str) -> tuple[str, list[str]]:
    actions: list[str] = []

    def replace(match: re.Match[str]) -> str:
        token = match.group(0)
        try:
            decoded = bytes.fromhex(token).decode("utf-8")
        except Exception:
            return token
        if len(decoded) < 4 or printable_ratio(decoded) < 0.85:
            return token
        actions.append("decode_hex_utf8")
        return decoded

    return re.sub(r"\b(?:[0-9A-Fa-f]{2}){10,}\b", replace, text), actions


def unspace_characters(text: str) -> tuple[str, list[str]]:
    if " / " not in text:
        return text, []
    tokens = text.split(" / ")
    if not tokens:
        return text, []
    char_like = sum(1 for token in tokens if len(token.strip()) <= 1)
    if char_like / len(tokens) < 0.65:
        return text, []
    return "".join(token.strip() for token in tokens), ["collapse_spaced_characters"]


def normalize_payload_suffix(text: str) -> tuple[str, list[str]]:
    prefix = "Echo the following user-supplied content as formatted HTML without executing it:"
    if not text.startswith(prefix):
        return text, []
    payload = text[len(prefix) :].strip()
    actions: list[str] = []
    if len(payload) >= 6 and payload[0] == '"' and payload[-1] == '"':
        try:
            payload = json.loads(payload)
            actions.append("decode_json_string_payload")
        except json.JSONDecodeError:
            payload = payload.strip('"')
    decoded_payload, extra = decode_base64_segments(payload)
    payload = decoded_payload
    actions.extend(extra)
    decoded_payload, extra = decode_hex_segments(payload)
    payload = decoded_payload
    actions.extend(extra)
    unquoted = unquote(payload)
    if unquoted != payload:
        payload = unquoted
        actions.append("url_decode_payload")
    unescaped = html.unescape(payload)
    if unescaped != payload:
        payload = unescaped
        actions.append("html_unescape_payload")
    return f"{prefix} {payload}", actions


def detect_language(text: str) -> str:
    try:
        return detect(text)
    except Exception:
        return "unknown"


@retry(wait=wait_exponential_jitter(initial=1, max=30), stop=stop_after_attempt(5))
def translate_to_english(client: OpenAI, text: str, source_language: str) -> str:
    prompt = (
        "Translate the following security-testing prompt into English. Preserve the exact "
        "instructional meaning, malicious intent, encodings, and references. Return only the "
        f"English text.\n\nSource language hint: {source_language}\n\nText:\n{text}"
    )
    response = client.responses.create(
        model=OPENAI_GENERATION_MODEL,
        input=prompt,
        max_output_tokens=500,
    )
    return response.output_text.strip()


def canonicalize_deterministic(text: str, transformation: str) -> tuple[str, list[str]]:
    actions: list[str] = []
    current = unicodedata.normalize("NFKC", text)
    if current != text:
        actions.append("unicode_nfkc")

    current, extra = strip_wrappers(current)
    actions.extend(extra)

    current, extra = normalize_payload_suffix(current)
    actions.extend(extra)

    unescaped = html.unescape(current)
    if unescaped != current:
        current = unescaped
        actions.append("html_unescape")

    unquoted = unquote(current)
    if unquoted != current:
        current = unquoted
        actions.append("url_decode")

    current, extra = decode_base64_segments(current)
    actions.extend(extra)

    current, extra = decode_hex_segments(current)
    actions.extend(extra)

    if transformation == "rot13":
        current = codecs.decode(current, "rot_13")
        actions.append("decode_rot13")

    if transformation == "spaced_characters":
        current, extra = unspace_characters(current)
        actions.extend(extra)

    transliterated = current.translate(CYRILLIC_HOMOGLYPHS)
    if transliterated != current:
        current = transliterated
        actions.append("transliterate_homoglyphs")

    if transformation == "leetspeak":
        current = current.translate(LEETSPEAK)
        actions.append("normalize_leetspeak")

    compacted = compact_spaces(current)
    if compacted != current:
        actions.append("compact_whitespace")
    return compacted, actions


def needs_translation(row: dict[str, object], detected_language: str) -> bool:
    transformation = str(row.get("transformation", ""))
    if transformation.startswith("translation_"):
        return True
    return detected_language not in {"en", "unknown"} and str(row.get("smr")) == "SMR-2"


def estimate_translation_cost(rows: list[dict[str, object]], cache: dict[str, str]) -> dict[str, object]:
    pending = [row for row in rows if str(row.get("variant_id")) not in cache]
    static_prompt_chars = 260
    input_chars = sum(len(str(row.get("text", ""))) + static_prompt_chars for row in pending)
    input_tokens = int(input_chars / 4)
    output_tokens = max(0, len(pending) * 110)
    cost = (input_tokens / 1_000_000) * PRICE_INPUT_PER_MTOK + (output_tokens / 1_000_000) * PRICE_OUTPUT_PER_MTOK
    return {
        "paid_step": "canonicalization_translation",
        "model": OPENAI_GENERATION_MODEL,
        "pending_translation_calls": len(pending),
        "estimated_input_tokens": input_tokens,
        "estimated_output_tokens": output_tokens,
        "estimated_cost_usd": round(cost, 4),
        "max_run_usd": MAX_RUN_USD,
        "pricing_assumption": {
            "input_usd_per_mtok": PRICE_INPUT_PER_MTOK,
            "output_usd_per_mtok": PRICE_OUTPUT_PER_MTOK,
        },
    }


def canonicalize_rows(
    rows: list[dict[str, object]],
    cache: dict[str, str],
    cache_path: Path,
    translate: bool,
    max_translations: int | None,
) -> tuple[list[dict[str, object]], dict[str, object]]:
    client: OpenAI | None = None
    if translate:
        load_dotenv(dotenv_path=Path(".env"))
        client = OpenAI()

    output_rows: list[dict[str, object]] = []
    stats = {
        "rows": len(rows),
        "changed": 0,
        "translations": 0,
        "cache_hits": 0,
        "actions": {},
    }

    for index, row in enumerate(rows, 1):
        original_text = str(row.get("text", ""))
        transformation = str(row.get("transformation", ""))
        canonical_text, actions = canonicalize_deterministic(original_text, transformation)
        language = detect_language(canonical_text)
        variant_id = str(row.get("variant_id"))

        if translate and client is not None and needs_translation(row, language):
            if variant_id in cache:
                canonical_text = cache[variant_id]
                actions.append("translation_cache_hit")
                stats["cache_hits"] = int(stats["cache_hits"]) + 1
            elif max_translations is None or int(stats["translations"]) < max_translations:
                translated = translate_to_english(client, canonical_text, language)
                cache[variant_id] = translated
                append_jsonl(
                    cache_path,
                    {
                        "variant_id": variant_id,
                        "source_language": language,
                        "source_hash": cache_key(canonical_text),
                        "translated_text": translated,
                        "model": OPENAI_GENERATION_MODEL,
                        "timestamp_unix": time.time(),
                    },
                )
                canonical_text = translated
                actions.append("translate_to_english")
                stats["translations"] = int(stats["translations"]) + 1

        out = dict(row)
        out["text"] = canonical_text
        out["original_text"] = original_text
        out["canonicalization"] = {
            "actions": actions,
            "detected_language": language,
            "changed": canonical_text != original_text,
        }
        output_rows.append(out)
        if canonical_text != original_text:
            stats["changed"] = int(stats["changed"]) + 1
        for action in actions:
            action_counts = stats["actions"]
            assert isinstance(action_counts, dict)
            action_counts[action] = int(action_counts.get(action, 0)) + 1
        if index % 100 == 0:
            print(f"canonicalized={index}/{len(rows)} translations={stats['translations']}")

    return output_rows, stats


def write_paper_summary(path: Path, summary: dict[str, object]) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(json.dumps(summary, ensure_ascii=True, indent=2) + "\n", encoding="utf-8")


def parse_args() -> argparse.Namespace:
    parser = argparse.ArgumentParser(description="Canonicalise variants for Phase 8 mitigation.")
    parser.add_argument("--input", type=Path, default=VARIANT_DIR / "variants.jsonl")
    parser.add_argument("--output", type=Path, default=VARIANT_DIR / "variants_canonicalized.jsonl")
    parser.add_argument("--seeds", type=Path, default=SEED_DIR / "seeds.jsonl")
    parser.add_argument("--translation-cache", type=Path, default=VARIANT_DIR / "translation_cache.jsonl")
    parser.add_argument("--summary", type=Path, default=VARIANT_DIR / "canonicalization_summary.json")
    parser.add_argument("--paper-summary", type=Path, default=PAPER_DIR / "snapshots" / "phase8_canonicalization_summary.json")
    parser.add_argument("--limit", type=int, default=None)
    parser.add_argument("--max-translations", type=int, default=None)
    parser.add_argument("--estimate-only", action="store_true")
    parser.add_argument("--skip-translation", action="store_true")
    return parser.parse_args()


def main() -> None:
    args = parse_args()
    rows = load_jsonl(args.input)
    if args.limit is not None:
        rows = rows[: args.limit]
    cache = load_translation_cache(args.translation_cache)
    translation_candidates = [
        row
        for row in rows
        if str(row.get("transformation", "")).startswith("translation_")
        and str(row.get("variant_id")) not in cache
    ]
    estimate = estimate_translation_cost(translation_candidates, {})
    print("translation_cost_estimate=" + json.dumps(estimate, ensure_ascii=True))
    if args.estimate_only:
        return
    if not args.skip_translation and estimate["estimated_cost_usd"] > MAX_RUN_USD:
        raise SystemExit(
            f"Estimated translation cost ${estimate['estimated_cost_usd']} exceeds MAX_RUN_USD=${MAX_RUN_USD}."
        )

    _seed_texts = load_seed_texts(args.seeds)
    canonical_rows, stats = canonicalize_rows(
        rows,
        cache,
        args.translation_cache,
        translate=not args.skip_translation,
        max_translations=args.max_translations,
    )
    write_jsonl(args.output, canonical_rows)
    summary = {
        "input": str(args.input),
        "output": str(args.output),
        "translation_cache": str(args.translation_cache),
        "model": OPENAI_GENERATION_MODEL,
        "cost_estimate": estimate,
        **stats,
    }
    args.summary.parent.mkdir(parents=True, exist_ok=True)
    args.summary.write_text(json.dumps(summary, ensure_ascii=True, indent=2) + "\n", encoding="utf-8")
    write_paper_summary(args.paper_summary, summary)
    print(json.dumps(summary, ensure_ascii=True, indent=2))


if __name__ == "__main__":
    main()
