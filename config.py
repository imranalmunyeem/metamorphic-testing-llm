"""Project-wide configuration for the SMR guardrail-testing framework."""

from __future__ import annotations

import os
from pathlib import Path

BASE_DIR = Path(__file__).resolve().parent
PAPER_DIR = Path(os.getenv("PAPER_DIR", BASE_DIR.parent / "smr-paper")).resolve()

DATA_DIR = BASE_DIR / "data"
SEED_DIR = DATA_DIR / "seeds"
VARIANT_DIR = DATA_DIR / "variants"
RESULTS_DIR = BASE_DIR / "results"
RAW_RESULTS_DIR = RESULTS_DIR / "raw"

MAX_RUN_USD = float(os.getenv("MAX_RUN_USD", "20.00"))

OPENAI_GENERATION_MODEL = os.getenv("OPENAI_GENERATION_MODEL", "gpt-5.4-mini")
OPENAI_JUDGE_MODEL = os.getenv("OPENAI_JUDGE_MODEL", OPENAI_GENERATION_MODEL)
OPENAI_MODERATION_MODEL = os.getenv("OPENAI_MODERATION_MODEL", "omni-moderation-latest")

PROTECTAI_MODEL = os.getenv(
    "PROTECTAI_MODEL",
    "protectai/deberta-v3-base-prompt-injection-v2",
)

LLM_REPETITIONS = int(os.getenv("LLM_REPETITIONS", "3"))
LOCAL_REPETITIONS = int(os.getenv("LOCAL_REPETITIONS", "1"))
DEFAULT_CONCURRENCY = int(os.getenv("DEFAULT_CONCURRENCY", "4"))
RANDOM_SEED = int(os.getenv("RANDOM_SEED", "20260610"))

