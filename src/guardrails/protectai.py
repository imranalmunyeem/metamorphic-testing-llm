"""ProtectAI prompt-injection classifier adapter."""

from __future__ import annotations

import time
from functools import lru_cache

from transformers import pipeline

from config import PROTECTAI_MODEL
from guardrails.base import GuardrailVerdict, clamp_score, timed_verdict


@lru_cache(maxsize=1)
def _classifier(model_name: str):
    return pipeline(
        "text-classification",
        model=model_name,
        tokenizer=model_name,
        truncation=True,
        top_k=None,
        device=-1,
    )


class ProtectAIGuardrail:
    name = "protectai"

    def __init__(self, model_name: str = PROTECTAI_MODEL) -> None:
        self.model_name = model_name

    def verdict(self, text: str) -> GuardrailVerdict:
        started = time.perf_counter()
        raw_result = _classifier(self.model_name)(text)
        scores = _normalize_scores(raw_result)
        injection_score = _injection_score(scores)
        blocked = injection_score >= 0.5
        return timed_verdict(
            self.name,
            started,
            blocked=blocked,
            score=injection_score,
            raw={
                "model": self.model_name,
                "scores": scores,
            },
        )


def _normalize_scores(raw_result: object) -> list[dict[str, object]]:
    if isinstance(raw_result, list) and raw_result and isinstance(raw_result[0], list):
        raw_result = raw_result[0]
    if isinstance(raw_result, dict):
        raw_result = [raw_result]
    rows: list[dict[str, object]] = []
    if isinstance(raw_result, list):
        for item in raw_result:
            if not isinstance(item, dict):
                continue
            rows.append(
                {
                    "label": str(item.get("label", "")),
                    "score": clamp_score(item.get("score")),
                }
            )
    return rows


def _injection_score(scores: list[dict[str, object]]) -> float:
    if not scores:
        return 0.0
    injection_labels = ("injection", "jailbreak", "malicious", "unsafe", "attack", "label_1")
    safe_labels = ("benign", "safe", "clean", "normal", "label_0")
    positive_scores = [
        float(row["score"])
        for row in scores
        if any(marker in str(row["label"]).casefold() for marker in injection_labels)
    ]
    if positive_scores:
        return clamp_score(max(positive_scores))
    safe_scores = [
        float(row["score"])
        for row in scores
        if any(marker in str(row["label"]).casefold() for marker in safe_labels)
    ]
    if safe_scores:
        return clamp_score(1.0 - max(safe_scores))
    return clamp_score(max(float(row["score"]) for row in scores))


def verdict(text: str) -> GuardrailVerdict:
    return ProtectAIGuardrail().verdict(text)

