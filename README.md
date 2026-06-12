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

## Phase 2 Variant Generation

Phase 2 generates SMR variants into the gitignored `data/variants/` folder and writes paper-facing artifacts into `..\smr-paper\`.

```powershell
.\.venv\Scripts\Activate.ps1
python src\generate_variants.py --limit-invariance-seeds 5 --output data\variants\smoke_variants.jsonl --rejects-output data\variants\smoke_rejects.jsonl --summary-output data\variants\smoke_run_summary.json --force
python src\generate_variants.py
python src\repair_variants.py
python src\audit_variants.py --dedupe
python src\make_phase2_artifacts.py
```

## Phase 3 Guardrail Adapter Smoke Test

Phase 3 adapters share the `Guardrail.verdict(text)` shape and can be smoke-tested on one benign and one malicious example:

```powershell
.\.venv\Scripts\Activate.ps1
python src\smoke_guardrails.py --guardrails all
```

This writes the paper-facing sanity table to `..\smr-paper\tables\baseline.csv`.

## Phase 4 Access-Control Mini-App

Phase 4 provides the SMR-5 role-differential mini-app and access-control scenarios:

```powershell
.\.venv\Scripts\Activate.ps1
python src\smoke_access_app.py --limit 3
python src\smoke_access_app.py
python src\make_phase4_artifacts.py
```

The limited command is for a quick smoke check. The full command writes the expanded access-control table to `..\smr-paper\tables\access_control_smoke.csv` and summary to `..\smr-paper\tables\access_control_summary.csv`; the paper example is saved as `..\smr-paper\figures\access_control_example.png`.

## Phase 5 Experiment Runner

Phase 5 runs every generated variant against the configured guardrails, appending each completed verdict to `results\raw\results.jsonl`. The runner is resumable: on restart it skips completed `(variant_id, guardrail, repetition)` keys.

```powershell
.\.venv\Scripts\Activate.ps1
python src\runner.py --limit-variants 10 --output results\raw\smoke_results.jsonl --summary-output results\raw\smoke_runner_summary.json --paper-summary ..\smr-paper\snapshots\phase5_smoke_runner_summary.json --paper-table ..\smr-paper\tables\runner_smoke_summary.csv --max-results 20 --workers 2 --force
python src\runner.py --limit-variants 10 --output results\raw\smoke_results.jsonl --summary-output results\raw\smoke_runner_summary.json --paper-summary ..\smr-paper\snapshots\phase5_smoke_runner_summary.json --paper-table ..\smr-paper\tables\runner_smoke_summary.csv --workers 2
python src\runner.py --estimate-only --workers 4
python src\runner.py --workers 4
```

For accounts with strict Moderation API quota windows, resume only that guardrail with smaller batches:

```powershell
python src\runner.py --guardrails openai_moderation --workers 1 --moderation-batch-size 8 --moderation-sleep-seconds 60 --moderation-rate-limit-cooldown-seconds 300 --moderation-max-rate-limit-stalls 24
```

The runner writes the paper-facing progress snapshot to `..\smr-paper\snapshots\phase5_runner_summary.json` and summary table to `..\smr-paper\tables\runner_summary.csv`.

## Phase 6 Metrics

Phase 6 scores the raw JSONL verdict ledger and writes reproducible CSV tables to `results\tables\`. The same tables are copied to `..\smr-paper\tables\` for manuscript use.

```powershell
.\.venv\Scripts\Activate.ps1
python src\metrics.py --input results\raw\smoke_results.jsonl --expected-from-results --output-dir results\tables\smoke --skip-paper-copy --bootstrap-iterations 200
python src\metrics.py --input results\raw\results.jsonl --variants data\variants\variants.jsonl --output-dir results\tables --paper-dir ..\smr-paper\tables --bootstrap-iterations 2000
```

The headline paper table is `..\smr-paper\tables\msir_by_guardrail_smr.csv`.

To compute agreement after a second human annotator returns a completed validation CSV:

```powershell
python src\compute_second_annotator_agreement.py --completed ..\smr-paper\tables\human_validation_second_annotator_completed.csv
```

This writes `..\smr-paper\tables\second_annotator_agreement_summary.csv`.

## Phase 7 Figures

Phase 7 regenerates all paper-facing figures and chart-support tables from saved Phase 6 outputs:

```powershell
.\.venv\Scripts\Activate.ps1
python src\make_figures.py
```

Figures are written as PNG and PDF pairs in `..\smr-paper\figures\`. The generated figure manifest is `..\smr-paper\tables\phase7_figure_manifest.csv`.

## Phase 8 Mitigation

Phase 8 canonicalises the variant corpus, reruns the guardrails on the canonicalised inputs, recomputes metrics, and refreshes the before/after mitigation figure:

```powershell
.\.venv\Scripts\Activate.ps1
python src\canonicalize.py --estimate-only
python src\canonicalize.py
python src\runner.py --variants data\variants\variants_canonicalized.jsonl --output results\raw\smoke_mitigated_results.jsonl --summary-output results\raw\smoke_mitigated_runner_summary.json --paper-summary ..\smr-paper\snapshots\phase8_smoke_runner_summary.json --paper-table ..\smr-paper\tables\runner_mitigated_smoke_summary.csv --limit-variants 10 --max-results 20 --workers 2 --force
python src\runner.py --variants data\variants\variants_canonicalized.jsonl --output results\raw\smoke_mitigated_results.jsonl --summary-output results\raw\smoke_mitigated_runner_summary.json --paper-summary ..\smr-paper\snapshots\phase8_smoke_runner_summary.json --paper-table ..\smr-paper\tables\runner_mitigated_smoke_summary.csv --limit-variants 10 --workers 2
python src\runner.py --variants data\variants\variants_canonicalized.jsonl --output results\raw\results_mitigated.jsonl --summary-output results\raw\runner_mitigated_summary.json --paper-summary ..\smr-paper\snapshots\phase8_runner_summary.json --paper-table ..\smr-paper\tables\runner_mitigated_summary.csv --estimate-only --workers 4
python src\metrics.py --input results\raw\results_mitigated.jsonl --variants data\variants\variants_canonicalized.jsonl --output-dir results\tables_mitigated --paper-dir ..\smr-paper\tables\mitigated --bootstrap-iterations 2000
python src\make_figures.py --mitigated-tables-dir results\tables_mitigated
```

The canonicalised variants and mitigated raw results are ignored because they are reproducible. The paper-facing before/after outputs are `..\smr-paper\figures\mitigation.png` and `..\smr-paper\tables\mitigation.csv`.

For the deterministic-only canonicalization ablation:

```powershell
python src\canonicalize.py --mode full --skip-translation --output data\variants\variants_canonicalized_deterministic.jsonl --summary data\variants\canonicalization_deterministic_summary.json --paper-summary ..\smr-paper\snapshots\phase8_canonicalization_deterministic_summary.json
python src\reuse_identical_results.py --ablation-variants data\variants\variants_canonicalized_deterministic.jsonl --ablation-results results\raw\results_ablation_deterministic.jsonl
python src\runner.py --variants data\variants\variants_canonicalized_deterministic.jsonl --output results\raw\results_ablation_deterministic.jsonl --summary-output results\raw\runner_ablation_deterministic_summary.json --paper-summary ..\smr-paper\snapshots\ablation_deterministic_runner_summary.json --paper-table ..\smr-paper\tables\runner_ablation_deterministic_summary.csv --workers 4
python src\compute_mcnemar.py --seed-results results\raw\seed_baseline_results.jsonl --variant-results results\raw\results_ablation_deterministic.jsonl --output-dir results\tables_ablation_deterministic --paper-dir ..\smr-paper\tables\ablation_deterministic
python src\metrics.py --input results\raw\results_ablation_deterministic.jsonl --variants data\variants\variants_canonicalized_deterministic.jsonl --output-dir results\tables_ablation_deterministic --paper-dir ..\smr-paper\tables\ablation_deterministic --bootstrap-iterations 2000
python src\make_ablation_summary.py
```

`reuse_identical_results.py` copies baseline verdicts only when the ablation input text is exactly identical to the original variant text, avoiding unnecessary reruns without changing the evaluated input.

## Phase 9 Reproducibility Gate

Phase 9 adds the one-command reproduction driver, freezes the paper run snapshot, and checks that every required paper artifact exists:

```powershell
.\.venv\Scripts\Activate.ps1
python reproduce.py --profile smoke --dry-run
python reproduce.py --profile full --dry-run
python src\make_run_snapshot.py
python src\check_paper_artifacts.py
```

The full reproduction command is:

```powershell
python reproduce.py --profile full --workers 4
```

The snapshot is written to `..\smr-paper\snapshots\run_snapshot.json`; the completeness report is `..\smr-paper\tables\paper_data_completeness.csv`.

## Git Hygiene

Commit reproducible code only. Do not commit `.env`, `results/`, `data/variants/`, large model caches, or anything from `smr-paper/`.
