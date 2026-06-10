# Metamorphic Security Testing for LLM Guardrails

This repository contains the reproducible code for a two-track project on Security Metamorphic Relations (SMRs) for LLM application guardrails. The paper-facing artifacts are written to the sibling `smr-paper/` folder and are never committed to this repository.

## Layout

- `smr-code/`: this git repository, containing source code, configuration, seed data, and reproduction scripts.
- `../smr-paper/`: manuscript-facing figures, tables, snapshots, and drafts. This folder is not a git repository.
- `data/seeds/`: small curated seed corpus, committed from Phase 1 onward.
- `data/variants/`: generated variants, ignored because they are reproducible.
- `results/`: raw and derived run outputs, ignored because they are reproducible and may be large.

## Setup

Run these commands from PowerShell inside `smr-code/`:

```powershell
py -3.12 -m venv .venv
.\.venv\Scripts\Activate.ps1
python -m pip install --upgrade pip
pip install -r requirements.txt
```

Python 3.12 is used for the venv because the current `llm-guard` package metadata supports Python versions below 3.13.

Create `.env` from `.env.example` and set `OPENAI_API_KEY`. Never commit `.env`.

```powershell
Copy-Item .env.example .env
notepad .env
python test_key.py
```

## Current Defaults

- Generation/judge model: `gpt-5.4-mini` by default, override with `OPENAI_GENERATION_MODEL` or `OPENAI_JUDGE_MODEL`.
- Moderation model: `omni-moderation-latest`.
- Budget cap: `MAX_RUN_USD=20.00` unless overridden.
- Paper output: `PAPER_DIR`, defaulting to the sibling `smr-paper/` folder.

## Phase 1 Seed Corpus

The normalized seed corpus is generated from public Hugging Face datasets plus small curated SMR-5/SMR-6 scenario sets:

```powershell
.\.venv\Scripts\Activate.ps1
python src\build_seeds.py
```

This writes `data/seeds/seeds.jsonl` and the redacted paper-facing sample table at `..\smr-paper\tables\seed_sample.csv`.

## Git Hygiene

Commit reproducible code only. Do not commit `.env`, `results/`, `data/variants/`, large model caches, or anything from `smr-paper/`.
