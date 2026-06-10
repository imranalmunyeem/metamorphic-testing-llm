"""Naive keyword/regex guardrail baseline."""

from __future__ import annotations

import re
import time

from guardrails.base import GuardrailVerdict, timed_verdict


class RegexBaselineGuardrail:
    name = "regex_baseline"

    def __init__(self) -> None:
        self.patterns = [
            re.compile(pattern, flags=re.IGNORECASE)
            for pattern in [
                r"\bignore (all )?(previous|prior|above) (instructions|rules|tasks)\b",
                r"\b(system|developer) prompt\b",
                r"\breveal\b.*\b(prompt|instruction|secret|credential|password)\b",
                r"\b(jailbreak|developer mode|do anything now|DAN)\b",
                r"\bbypass\b.*\b(guardrail|filter|policy|safety|restriction)\b",
                r"\bmalware\b",
                r"\bsteal\b.*\b(password|credential|token|secret)\b",
                r"\bexfiltrate\b",
                r"\bbase64\b.*\bdecode\b.*\bfollow\b",
            ]
        ]

    def verdict(self, text: str) -> GuardrailVerdict:
        started = time.perf_counter()
        matches = [pattern.pattern for pattern in self.patterns if pattern.search(text)]
        score = min(1.0, len(matches) / 3)
        return timed_verdict(
            self.name,
            started,
            blocked=bool(matches),
            score=score,
            raw={"matches": matches},
        )


def verdict(text: str) -> GuardrailVerdict:
    return RegexBaselineGuardrail().verdict(text)

