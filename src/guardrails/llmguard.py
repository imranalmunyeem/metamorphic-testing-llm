"""LLM Guard scanner adapter."""

from __future__ import annotations

import time
from functools import lru_cache

from llm_guard.input_scanners import PromptInjection, Toxicity

from guardrails.base import GuardrailVerdict, clamp_score, timed_verdict


@lru_cache(maxsize=1)
def _prompt_injection_scanner() -> PromptInjection:
    return PromptInjection()


@lru_cache(maxsize=1)
def _toxicity_scanner() -> Toxicity:
    return Toxicity()


class LLMGuardGuardrail:
    name = "llmguard"

    def __init__(self) -> None:
        self.prompt_injection = _prompt_injection_scanner()
        self.toxicity = _toxicity_scanner()

    def verdict(self, text: str) -> GuardrailVerdict:
        started = time.perf_counter()
        pi_sanitized, pi_valid, pi_score = self.prompt_injection.scan(text)
        tox_sanitized, tox_valid, tox_score = self.toxicity.scan(text)
        blocked = not (pi_valid and tox_valid)
        score = max(clamp_score(pi_score), clamp_score(tox_score))
        return timed_verdict(
            self.name,
            started,
            blocked=blocked,
            score=score,
            raw={
                "prompt_injection": {
                    "is_valid": bool(pi_valid),
                    "score": clamp_score(pi_score),
                    "sanitized_changed": pi_sanitized != text,
                },
                "toxicity": {
                    "is_valid": bool(tox_valid),
                    "score": clamp_score(tox_score),
                    "sanitized_changed": tox_sanitized != text,
                },
            },
        )


def verdict(text: str) -> GuardrailVerdict:
    return LLMGuardGuardrail().verdict(text)

