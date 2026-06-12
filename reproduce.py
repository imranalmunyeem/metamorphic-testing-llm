"""One-command reproduction driver for the SMR guardrail study."""

from __future__ import annotations

import argparse
import subprocess
import sys
from pathlib import Path


ROOT = Path(__file__).resolve().parent
PYTHON = sys.executable


def run(command: list[str], dry_run: bool) -> None:
    printable = " ".join(command)
    print(f"run={printable}")
    if not dry_run:
        subprocess.run(command, cwd=ROOT, check=True)


def run_smoke(args: argparse.Namespace) -> None:
    run([PYTHON, "test_key.py"], args.dry_run)
    run([PYTHON, "src\\smoke_guardrails.py", "--guardrails", "all"], args.dry_run)
    run([PYTHON, "src\\smoke_access_app.py", "--limit", "3"], args.dry_run)
    run([PYTHON, "src\\make_phase4_artifacts.py"], args.dry_run)
    run(
        [
            PYTHON,
            "src\\runner.py",
            "--limit-variants",
            "10",
            "--output",
            "results\\raw\\smoke_results.jsonl",
            "--summary-output",
            "results\\raw\\smoke_runner_summary.json",
            "--paper-summary",
            "..\\smr-paper\\snapshots\\phase5_smoke_runner_summary.json",
            "--paper-table",
            "..\\smr-paper\\tables\\runner_smoke_summary.csv",
            "--max-results",
            "20",
            "--workers",
            str(args.workers),
            "--force",
        ],
        args.dry_run,
    )
    run(
        [
            PYTHON,
            "src\\runner.py",
            "--limit-variants",
            "10",
            "--output",
            "results\\raw\\smoke_results.jsonl",
            "--summary-output",
            "results\\raw\\smoke_runner_summary.json",
            "--paper-summary",
            "..\\smr-paper\\snapshots\\phase5_smoke_runner_summary.json",
            "--paper-table",
            "..\\smr-paper\\tables\\runner_smoke_summary.csv",
            "--workers",
            str(args.workers),
        ],
        args.dry_run,
    )
    run(
        [
            PYTHON,
            "src\\metrics.py",
            "--input",
            "results\\raw\\smoke_results.jsonl",
            "--expected-from-results",
            "--output-dir",
            "results\\tables\\smoke",
            "--skip-paper-copy",
            "--bootstrap-iterations",
            "200",
        ],
        args.dry_run,
    )


def run_full(args: argparse.Namespace) -> None:
    run([PYTHON, "src\\build_seeds.py"], args.dry_run)
    run([PYTHON, "src\\generate_variants.py"], args.dry_run)
    run([PYTHON, "src\\repair_variants.py"], args.dry_run)
    run([PYTHON, "src\\audit_variants.py", "--dedupe"], args.dry_run)
    run([PYTHON, "src\\make_phase2_artifacts.py"], args.dry_run)
    run([PYTHON, "src\\smoke_guardrails.py", "--guardrails", "all"], args.dry_run)
    run([PYTHON, "src\\smoke_access_app.py"], args.dry_run)
    run([PYTHON, "src\\make_phase4_artifacts.py"], args.dry_run)
    run([PYTHON, "src\\runner.py", "--estimate-only", "--workers", str(args.workers)], args.dry_run)
    run([PYTHON, "src\\runner.py", "--workers", str(args.workers)], args.dry_run)
    run(
        [
            PYTHON,
            "src\\metrics.py",
            "--input",
            "results\\raw\\results.jsonl",
            "--variants",
            "data\\variants\\variants.jsonl",
            "--output-dir",
            "results\\tables",
            "--paper-dir",
            "..\\smr-paper\\tables",
            "--bootstrap-iterations",
            str(args.bootstrap_iterations),
        ],
        args.dry_run,
    )
    run([PYTHON, "src\\canonicalize.py", "--estimate-only"], args.dry_run)
    run([PYTHON, "src\\canonicalize.py"], args.dry_run)
    run(
        [
            PYTHON,
            "src\\canonicalize.py",
            "--mode",
            "full",
            "--skip-translation",
            "--output",
            "data\\variants\\variants_canonicalized_deterministic.jsonl",
            "--summary",
            "data\\variants\\canonicalization_deterministic_summary.json",
            "--paper-summary",
            "..\\smr-paper\\snapshots\\phase8_canonicalization_deterministic_summary.json",
        ],
        args.dry_run,
    )
    run(
        [
            PYTHON,
            "src\\reuse_identical_results.py",
            "--ablation-variants",
            "data\\variants\\variants_canonicalized_deterministic.jsonl",
            "--ablation-results",
            "results\\raw\\results_ablation_deterministic.jsonl",
        ],
        args.dry_run,
    )
    run(
        [
            PYTHON,
            "src\\runner.py",
            "--variants",
            "data\\variants\\variants_canonicalized.jsonl",
            "--output",
            "results\\raw\\results_mitigated.jsonl",
            "--summary-output",
            "results\\raw\\runner_mitigated_summary.json",
            "--paper-summary",
            "..\\smr-paper\\snapshots\\phase8_runner_summary.json",
            "--paper-table",
            "..\\smr-paper\\tables\\runner_mitigated_summary.csv",
            "--estimate-only",
            "--workers",
            str(args.workers),
        ],
        args.dry_run,
    )
    run(
        [
            PYTHON,
            "src\\runner.py",
            "--variants",
            "data\\variants\\variants_canonicalized.jsonl",
            "--output",
            "results\\raw\\results_mitigated.jsonl",
            "--summary-output",
            "results\\raw\\runner_mitigated_summary.json",
            "--paper-summary",
            "..\\smr-paper\\snapshots\\phase8_runner_summary.json",
            "--paper-table",
            "..\\smr-paper\\tables\\runner_mitigated_summary.csv",
            "--workers",
            str(args.workers),
        ],
        args.dry_run,
    )
    run(
        [
            PYTHON,
            "src\\metrics.py",
            "--input",
            "results\\raw\\results_mitigated.jsonl",
            "--variants",
            "data\\variants\\variants_canonicalized.jsonl",
            "--output-dir",
            "results\\tables_mitigated",
            "--paper-dir",
            "..\\smr-paper\\tables\\mitigated",
            "--bootstrap-iterations",
            str(args.bootstrap_iterations),
        ],
        args.dry_run,
    )
    run(
        [
            PYTHON,
            "src\\runner.py",
            "--variants",
            "data\\variants\\variants_canonicalized_deterministic.jsonl",
            "--output",
            "results\\raw\\results_ablation_deterministic.jsonl",
            "--summary-output",
            "results\\raw\\runner_ablation_deterministic_summary.json",
            "--paper-summary",
            "..\\smr-paper\\snapshots\\ablation_deterministic_runner_summary.json",
            "--paper-table",
            "..\\smr-paper\\tables\\runner_ablation_deterministic_summary.csv",
            "--estimate-only",
            "--workers",
            str(args.workers),
        ],
        args.dry_run,
    )
    run(
        [
            PYTHON,
            "src\\runner.py",
            "--variants",
            "data\\variants\\variants_canonicalized_deterministic.jsonl",
            "--output",
            "results\\raw\\results_ablation_deterministic.jsonl",
            "--summary-output",
            "results\\raw\\runner_ablation_deterministic_summary.json",
            "--paper-summary",
            "..\\smr-paper\\snapshots\\ablation_deterministic_runner_summary.json",
            "--paper-table",
            "..\\smr-paper\\tables\\runner_ablation_deterministic_summary.csv",
            "--workers",
            str(args.workers),
        ],
        args.dry_run,
    )
    run(
        [
            PYTHON,
            "src\\metrics.py",
            "--input",
            "results\\raw\\results_ablation_deterministic.jsonl",
            "--variants",
            "data\\variants\\variants_canonicalized_deterministic.jsonl",
            "--output-dir",
            "results\\tables_ablation_deterministic",
            "--paper-dir",
            "..\\smr-paper\\tables\\ablation_deterministic",
            "--bootstrap-iterations",
            str(args.bootstrap_iterations),
        ],
        args.dry_run,
    )
    run([PYTHON, "src\\make_seed_baseline.py"], args.dry_run)
    run(
        [
            PYTHON,
            "src\\runner.py",
            "--variants",
            "data\\variants\\seed_baseline.jsonl",
            "--output",
            "results\\raw\\seed_baseline_results.jsonl",
            "--summary-output",
            "results\\raw\\seed_baseline_runner_summary.json",
            "--paper-summary",
            "..\\smr-paper\\snapshots\\seed_baseline_runner_summary.json",
            "--paper-table",
            "..\\smr-paper\\tables\\seed_baseline_runner_summary.csv",
            "--workers",
            str(args.workers),
        ],
        args.dry_run,
    )
    run(
        [
            PYTHON,
            "src\\compute_mcnemar.py",
            "--seed-results",
            "results\\raw\\seed_baseline_results.jsonl",
            "--variant-results",
            "results\\raw\\results.jsonl",
            "--output-dir",
            "results\\tables",
            "--paper-dir",
            "..\\smr-paper\\tables",
        ],
        args.dry_run,
    )
    run(
        [
            PYTHON,
            "src\\compute_mcnemar.py",
            "--seed-results",
            "results\\raw\\seed_baseline_results.jsonl",
            "--variant-results",
            "results\\raw\\results_ablation_deterministic.jsonl",
            "--output-dir",
            "results\\tables_ablation_deterministic",
            "--paper-dir",
            "..\\smr-paper\\tables\\ablation_deterministic",
        ],
        args.dry_run,
    )
    run(
        [
            PYTHON,
            "src\\compute_mcnemar.py",
            "--seed-results",
            "results\\raw\\seed_baseline_results.jsonl",
            "--variant-results",
            "results\\raw\\results_mitigated.jsonl",
            "--output-dir",
            "results\\tables_mitigated",
            "--paper-dir",
            "..\\smr-paper\\tables\\mitigated",
        ],
        args.dry_run,
    )
    run(
        [
            PYTHON,
            "src\\metrics.py",
            "--input",
            "results\\raw\\results.jsonl",
            "--variants",
            "data\\variants\\variants.jsonl",
            "--output-dir",
            "results\\tables",
            "--paper-dir",
            "..\\smr-paper\\tables",
            "--bootstrap-iterations",
            str(args.bootstrap_iterations),
        ],
        args.dry_run,
    )
    run(
        [
            PYTHON,
            "src\\metrics.py",
            "--input",
            "results\\raw\\results_ablation_deterministic.jsonl",
            "--variants",
            "data\\variants\\variants_canonicalized_deterministic.jsonl",
            "--output-dir",
            "results\\tables_ablation_deterministic",
            "--paper-dir",
            "..\\smr-paper\\tables\\ablation_deterministic",
            "--bootstrap-iterations",
            str(args.bootstrap_iterations),
        ],
        args.dry_run,
    )
    run(
        [
            PYTHON,
            "src\\metrics.py",
            "--input",
            "results\\raw\\results_mitigated.jsonl",
            "--variants",
            "data\\variants\\variants_canonicalized.jsonl",
            "--output-dir",
            "results\\tables_mitigated",
            "--paper-dir",
            "..\\smr-paper\\tables\\mitigated",
            "--bootstrap-iterations",
            str(args.bootstrap_iterations),
        ],
        args.dry_run,
    )
    run([PYTHON, "src\\make_figures.py", "--mitigated-tables-dir", "results\\tables_mitigated"], args.dry_run)
    run([PYTHON, "src\\make_ablation_summary.py"], args.dry_run)
    run([PYTHON, "src\\make_experiment_details.py"], args.dry_run)
    run([PYTHON, "src\\make_run_snapshot.py"], args.dry_run)
    run([PYTHON, "src\\check_paper_artifacts.py"], args.dry_run)


def parse_args() -> argparse.Namespace:
    parser = argparse.ArgumentParser(description="Reproduce the SMR guardrail-testing artifacts.")
    parser.add_argument("--profile", choices=["smoke", "full"], default="full")
    parser.add_argument("--workers", type=int, default=4)
    parser.add_argument("--bootstrap-iterations", type=int, default=2000)
    parser.add_argument("--dry-run", action="store_true")
    return parser.parse_args()


def main() -> None:
    args = parse_args()
    if args.profile == "smoke":
        run_smoke(args)
    else:
        run_full(args)


if __name__ == "__main__":
    main()
