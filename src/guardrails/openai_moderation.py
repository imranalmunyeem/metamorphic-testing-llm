"""OpenAI Moderation API guardrail adapter."""

from __future__ import annotations

import time
from pathlib import Path

from dotenv import load_dotenv
from openai import OpenAI

from config import OPENAI_MODERATION_MODEL
from guardrails.base import GuardrailVerdict, clamp_score, timed_verdict


class OpenAIModerationGuardrail:
    name = "openai_moderation"

    def __init__(self, model: str = OPENAI_MODERATION_MODEL) -> None:
        load_dotenv(dotenv_path=Path(".env"))
        self.model = model
        self.client = OpenAI()

    def verdict(self, text: str) -> GuardrailVerdict:
        started = time.perf_counter()
        response = self.client.moderations.create(model=self.model, input=text)
        result = response.results[0]
        raw = result.model_dump(mode="json")
        category_scores = raw.get("category_scores", {})
        max_score = max((float(score) for score in category_scores.values()), default=0.0)
        return timed_verdict(
            self.name,
            started,
            blocked=bool(raw.get("flagged")),
            score=clamp_score(max_score),
            raw={
                "model": self.model,
                "flagged": raw.get("flagged"),
                "categories": raw.get("categories", {}),
                "max_category_score": max_score,
            },
        )


def verdict(text: str) -> GuardrailVerdict:
    return OpenAIModerationGuardrail().verdict(text)

