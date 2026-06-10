"""Common guardrail adapter interface."""

from __future__ import annotations

import time
from dataclasses import asdict, dataclass
from typing import Any, Protocol


@dataclass(frozen=True)
class GuardrailVerdict:
    blocked: bool
    score: float
    raw: Any
    guardrail: str
    latency_ms: float

    def to_dict(self) -> dict[str, Any]:
        return asdict(self)


class Guardrail(Protocol):
    name: str

    def verdict(self, text: str) -> GuardrailVerdict:
        """Classify one prompt and return a normalized block/allow verdict."""


def clamp_score(score: float | int | None) -> float:
    if score is None:
        return 0.0
    try:
        value = float(score)
    except (TypeError, ValueError):
        return 0.0
    return max(0.0, min(1.0, value))


def timed_verdict(name: str, started: float, blocked: bool, score: float, raw: Any) -> GuardrailVerdict:
    return GuardrailVerdict(
        blocked=bool(blocked),
        score=clamp_score(score),
        raw=raw,
        guardrail=name,
        latency_ms=round((time.perf_counter() - started) * 1000, 3),
    )

