"""Generate Phase 7 paper figures and chart-support tables."""

from __future__ import annotations

import argparse
import csv
import json
import sys
import textwrap
from pathlib import Path

import matplotlib

matplotlib.use("Agg")

import matplotlib.pyplot as plt
import numpy as np
import pandas as pd
import seaborn as sns
from matplotlib.patches import FancyArrowPatch, FancyBboxPatch

sys.path.insert(0, str(Path(__file__).resolve().parent))
sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

from config import PAPER_DIR, RAW_RESULTS_DIR, RESULTS_DIR, VARIANT_DIR  # noqa: E402
from make_phase4_artifacts import load_rows, make_example_figure  # noqa: E402
from metrics import collapse_variant_outcomes, dedupe_results, load_jsonl, variant_metadata  # noqa: E402


GUARDRAIL_ORDER = [
    "regex_baseline",
    "openai_moderation",
    "protectai",
    "llmguard",
    "llm_judge",
]

GUARDRAIL_LABELS = {
    "regex_baseline": "Regex",
    "openai_moderation": "OpenAI\nModeration",
    "protectai": "ProtectAI",
    "llmguard": "LLM Guard",
    "llm_judge": "LLM Judge",
}

SMR_ORDER = ["SMR-1", "SMR-2", "SMR-3", "SMR-4", "SMR-5", "SMR-6", "SMR-7"]

SMR_LABELS = {
    "SMR-1": "SMR-1\nParaphrase",
    "SMR-2": "SMR-2\nTranslation",
    "SMR-3": "SMR-3\nEncoding",
    "SMR-4": "SMR-4\nFormatting",
    "SMR-5": "SMR-5\nPrivilege",
    "SMR-6": "SMR-6\nComposition",
    "SMR-7": "SMR-7\nOutput",
}

OWASP_ORDER = [
    "LLM01 Prompt Injection",
    "LLM02 Sensitive Information Disclosure",
    "LLM05 Improper Output Handling",
    "LLM06 Excessive Agency",
    "LLM07 System Prompt Leakage",
]

PALETTE = {
    "regex_baseline": "#4c78a8",
    "openai_moderation": "#f58518",
    "protectai": "#54a24b",
    "llmguard": "#b279a2",
    "llm_judge": "#e45756",
}


def read_csv(path: Path) -> pd.DataFrame:
    if not path.exists():
        raise FileNotFoundError(f"Missing required table: {path}")
    return pd.read_csv(path)


def write_csv(path: Path, rows: list[dict[str, object]], fieldnames: list[str]) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    with path.open("w", encoding="utf-8", newline="") as handle:
        writer = csv.DictWriter(handle, fieldnames=fieldnames, extrasaction="ignore")
        writer.writeheader()
        for row in rows:
            writer.writerow(row)


def save_figure(fig: plt.Figure, figures_dir: Path, stem: str) -> dict[str, object]:
    figures_dir.mkdir(parents=True, exist_ok=True)
    png_path = figures_dir / f"{stem}.png"
    pdf_path = figures_dir / f"{stem}.pdf"
    fig.savefig(png_path, dpi=300, bbox_inches="tight", facecolor="white")
    fig.savefig(pdf_path, bbox_inches="tight", facecolor="white")
    plt.close(fig)
    return {
        "figure": stem,
        "png": str(png_path),
        "png_bytes": png_path.stat().st_size,
        "pdf": str(pdf_path),
        "pdf_bytes": pdf_path.stat().st_size,
    }


def set_common_style() -> None:
    sns.set_theme(style="whitegrid")
    plt.rcParams.update(
        {
            "font.family": "DejaVu Sans",
            "axes.titlesize": 14,
            "axes.labelsize": 11,
            "xtick.labelsize": 9,
            "ytick.labelsize": 9,
            "legend.fontsize": 9,
            "figure.dpi": 120,
        }
    )


def ordered_guardrail_frame(df: pd.DataFrame) -> pd.DataFrame:
    order = {name: idx for idx, name in enumerate(GUARDRAIL_ORDER)}
    return df.assign(_order=df["guardrail"].map(order)).sort_values("_order").drop(columns="_order")


def write_mermaid_sources(figures_dir: Path) -> None:
    architecture = """flowchart LR
    A[Seed corpus] --> B[SMR transformations]
    B --> C[Variant validation]
    C --> D[Guardrail adapters]
    D --> E[Raw verdict ledger]
    E --> F[Metrics and figures]
    F --> G[Canonicalisation mitigation]
    G --> D
"""
    taxonomy = """flowchart TB
    T[Security Metamorphic Relations] --> I[Invariance relations]
    T --> D[Differential relations]
    T --> O[Output-handling relation]
    I --> S1[SMR-1 Paraphrase / LLM01]
    I --> S2[SMR-2 Translation / LLM01]
    I --> S3[SMR-3 Encoding / LLM01]
    I --> S4[SMR-4 Formatting / LLM01]
    D --> S5[SMR-5 Privilege / LLM02 LLM06 LLM07]
    D --> S6[SMR-6 Composition / LLM01]
    O --> S7[SMR-7 Sanitisation / LLM05]
"""
    figures_dir.mkdir(parents=True, exist_ok=True)
    (figures_dir / "architecture.mmd").write_text(architecture, encoding="utf-8")
    (figures_dir / "smr_taxonomy.mmd").write_text(taxonomy, encoding="utf-8")


def add_box(
    ax: plt.Axes,
    xy: tuple[float, float],
    width: float,
    height: float,
    text: str,
    facecolor: str,
    edgecolor: str = "#2f3b4a",
    fontsize: int = 10,
) -> None:
    box = FancyBboxPatch(
        xy,
        width,
        height,
        boxstyle="round,pad=0.02,rounding_size=0.04",
        linewidth=1.2,
        edgecolor=edgecolor,
        facecolor=facecolor,
    )
    ax.add_patch(box)
    ax.text(
        xy[0] + width / 2,
        xy[1] + height / 2,
        text,
        ha="center",
        va="center",
        fontsize=fontsize,
        weight="bold",
        color="#1f2933",
        wrap=True,
    )


def add_arrow(ax: plt.Axes, start: tuple[float, float], end: tuple[float, float], rad: float = 0.0) -> None:
    arrow = FancyArrowPatch(
        start,
        end,
        arrowstyle="-|>",
        mutation_scale=14,
        linewidth=1.4,
        color="#405166",
        connectionstyle=f"arc3,rad={rad}",
    )
    ax.add_patch(arrow)


def architecture_figure(figures_dir: Path) -> dict[str, object]:
    fig, ax = plt.subplots(figsize=(13.5, 3.4))
    ax.set_xlim(0, 12)
    ax.set_ylim(0, 3.1)
    ax.axis("off")
    labels = [
        "Seed\ncorpus",
        "SMR\ntransforms",
        "Variant\nvalidation",
        "Guardrail\nadapters",
        "Raw verdict\nledger",
        "Metrics and\nfigures",
    ]
    colors = ["#d9e8fb", "#e8f4d9", "#fff2cc", "#f7d9e3", "#e1ddf4", "#d7f0ee"]
    xs = [0.3, 2.15, 4.0, 5.85, 7.7, 9.55]
    for x, label, color in zip(xs, labels, colors):
        add_box(ax, (x, 1.42), 1.45, 0.9, label, color)
    for x in xs[:-1]:
        add_arrow(ax, (x + 1.45, 1.87), (x + 1.85, 1.87))
    add_box(ax, (7.65, 0.25), 2.25, 0.72, "Canonicalisation\nmitigation (Phase 8)", "#f8e3c4", fontsize=9)
    add_arrow(ax, (10.25, 1.42), (9.0, 0.97), rad=0.08)
    add_arrow(ax, (7.65, 0.61), (6.55, 1.42), rad=-0.18)
    ax.set_title("SMR Guardrail Testing Pipeline", loc="left", weight="bold", pad=12)
    ax.text(
        0.3,
        0.08,
        "All raw verdicts are appended before scoring; paper figures are regenerated from saved tables.",
        fontsize=9,
        color="#52616f",
    )
    return save_figure(fig, figures_dir, "architecture")


def taxonomy_figure(figures_dir: Path) -> dict[str, object]:
    fig, ax = plt.subplots(figsize=(13.0, 6.2))
    ax.set_xlim(0, 12)
    ax.set_ylim(0, 7)
    ax.axis("off")
    add_box(ax, (4.1, 6.15), 3.8, 0.6, "Security Metamorphic Relations", "#d7f0ee", fontsize=12)
    families = [
        ("Invariance\nsame malicious intent -> same verdict", 0.45, "#d9e8fb"),
        ("Differential\nrelated inputs -> ordered verdict/content", 4.25, "#fff2cc"),
        ("Output handling\nencoded payload -> same sanitisation", 8.05, "#f7d9e3"),
    ]
    for label, x, color in families:
        add_box(ax, (x, 5.0), 3.4, 0.72, label, color, fontsize=9)
        add_arrow(ax, (6.0, 6.15), (x + 1.7, 5.72), rad=0.08 if x < 4 else -0.08)

    invariance = [
        ("SMR-1  Paraphrase  LLM01", 0.9, 4.1),
        ("SMR-2  Translation  LLM01", 0.9, 3.3),
        ("SMR-3  Encoding  LLM01", 0.9, 2.5),
        ("SMR-4  Formatting  LLM01", 0.9, 1.7),
    ]
    for text, x, y in invariance:
        add_box(ax, (x, y), 2.5, 0.55, text, "#eef5ff", fontsize=8)
    add_arrow(ax, (2.15, 5.0), (2.15, 4.65), rad=0.0)
    add_arrow(ax, (2.15, 4.1), (2.15, 3.85), rad=0.0)
    add_arrow(ax, (2.15, 3.3), (2.15, 3.05), rad=0.0)
    add_arrow(ax, (2.15, 2.5), (2.15, 2.25), rad=0.0)
    differential = [
        ("SMR-5  Privilege  LLM02 LLM06 LLM07", 4.75, 4.1),
        ("SMR-6  Composition  LLM01", 4.75, 3.3),
    ]
    for text, x, y in differential:
        add_box(ax, (x, y), 2.5, 0.55, text, "#fff7df", fontsize=8)
    add_arrow(ax, (5.95, 5.0), (5.95, 4.65), rad=0.0)
    add_arrow(ax, (5.95, 4.1), (5.95, 3.85), rad=0.0)
    add_box(ax, (8.5, 3.7), 2.8, 0.7, "SMR-7  Output sanitisation  LLM05", "#fdebf1", fontsize=8)
    add_arrow(ax, (9.75, 5.0), (9.9, 4.4), rad=0.0)
    ax.set_title("SMR Taxonomy and OWASP LLM Top 10 Mapping", loc="left", weight="bold", pad=12)
    return save_figure(fig, figures_dir, "smr_taxonomy")


def msir_per_guardrail_figure(tables_dir: Path, figures_dir: Path) -> dict[str, object]:
    df = ordered_guardrail_frame(read_csv(tables_dir / "msir_by_guardrail.csv"))
    x = np.arange(len(df))
    yerr = np.vstack([df["mean"] - df["ci95_low"], df["ci95_high"] - df["mean"]])
    fig, ax = plt.subplots(figsize=(9.2, 5.0))
    colors = [PALETTE.get(name, "#777777") for name in df["guardrail"]]
    ax.bar(x, df["mean"], color=colors, edgecolor="#2f3b4a", linewidth=0.8)
    ax.errorbar(x, df["mean"], yerr=yerr, fmt="none", ecolor="#1f2933", elinewidth=1.2, capsize=4)
    ax.set_xticks(x, [GUARDRAIL_LABELS.get(name, name) for name in df["guardrail"]])
    ax.set_ylabel("MSIR")
    ax.set_ylim(0, min(1.0, max(df["ci95_high"].max() + 0.08, 0.5)))
    ax.set_title("Metamorphic Security Inconsistency Rate by Guardrail", weight="bold")
    for idx, row in df.reset_index(drop=True).iterrows():
        ax.text(idx, row["mean"] + 0.025, f"{row['mean']:.2f}", ha="center", va="bottom", fontsize=9)
        if int(row.get("incomplete_sets", 0)) > 0:
            ax.text(idx, 0.02, "partial", ha="center", va="bottom", fontsize=8, color="#7a3b00")
    ax.grid(axis="y", alpha=0.35)
    return save_figure(fig, figures_dir, "msir_per_guardrail")


def heatmap_figure(tables_dir: Path, figures_dir: Path) -> dict[str, object]:
    df = read_csv(tables_dir / "msir_by_guardrail_smr.csv")
    matrix = (
        df.pivot(index="guardrail", columns="smr", values="mean")
        .reindex(index=GUARDRAIL_ORDER, columns=SMR_ORDER)
        .rename(index=GUARDRAIL_LABELS, columns=SMR_LABELS)
    )
    fig, ax = plt.subplots(figsize=(11.0, 5.8))
    sns.heatmap(
        matrix,
        ax=ax,
        vmin=0,
        vmax=1,
        cmap="YlOrRd",
        linewidths=0.8,
        linecolor="white",
        annot=True,
        fmt=".2f",
        cbar_kws={"label": "MSIR"},
    )
    ax.set_xlabel("")
    ax.set_ylabel("")
    ax.set_title("Guardrail x SMR Inconsistency Heatmap", weight="bold")
    return save_figure(fig, figures_dir, "heatmap")


def split_owasp_categories(value: object) -> list[str]:
    parts = [part.strip() for part in str(value).split(";") if part.strip()]
    return parts or ["Unmapped"]


def owasp_breakdown_table(tables_dir: Path, paper_tables_dir: Path) -> pd.DataFrame:
    df = read_csv(tables_dir / "defense_gap_by_seed.csv")
    rows: list[dict[str, object]] = []
    for _, row in df.iterrows():
        for category in split_owasp_categories(row["owasp_category"]):
            rows.append(
                {
                    "guardrail": row["guardrail"],
                    "owasp_category": category,
                    "inconsistent_sets": int(str(row["inconsistent"]).lower() == "true"),
                    "seed_smr_sets": 1,
                }
            )
    exploded = pd.DataFrame(rows)
    summary = (
        exploded.groupby(["guardrail", "owasp_category"], as_index=False)
        .agg({"inconsistent_sets": "sum", "seed_smr_sets": "sum"})
        .assign(msir=lambda frame: frame["inconsistent_sets"] / frame["seed_smr_sets"])
    )
    all_index = pd.MultiIndex.from_product([GUARDRAIL_ORDER, OWASP_ORDER], names=["guardrail", "owasp_category"])
    summary = (
        summary.set_index(["guardrail", "owasp_category"])
        .reindex(all_index, fill_value=0)
        .reset_index()
    )
    summary["msir"] = np.where(
        summary["seed_smr_sets"] > 0,
        summary["inconsistent_sets"] / summary["seed_smr_sets"],
        0.0,
    )
    output = paper_tables_dir / "owasp_breakdown.csv"
    output.parent.mkdir(parents=True, exist_ok=True)
    summary.to_csv(output, index=False)
    return summary


def owasp_breakdown_figure(tables_dir: Path, paper_tables_dir: Path, figures_dir: Path) -> dict[str, object]:
    df = owasp_breakdown_table(tables_dir, paper_tables_dir)
    fig, ax = plt.subplots(figsize=(12.5, 5.4))
    sns.barplot(
        data=df,
        x="owasp_category",
        y="inconsistent_sets",
        hue="guardrail",
        hue_order=GUARDRAIL_ORDER,
        palette=PALETTE,
        ax=ax,
        edgecolor="#2f3b4a",
        linewidth=0.4,
    )
    ax.set_xticks(range(len(OWASP_ORDER)))
    ax.set_xticklabels(
        ["LLM01\nPrompt\nInjection", "LLM02\nSensitive\nDisclosure", "LLM05\nOutput\nHandling", "LLM06\nExcessive\nAgency", "LLM07\nPrompt\nLeakage"],
        rotation=0,
    )
    ax.set_ylabel("Inconsistent seed-SMR sets")
    ax.set_xlabel("")
    ax.set_title("Metamorphic Violations by OWASP LLM Top 10 Category", weight="bold")
    handles, labels = ax.get_legend_handles_labels()
    ax.legend(handles, [GUARDRAIL_LABELS.get(label, label).replace("\n", " ") for label in labels], title="")
    return save_figure(fig, figures_dir, "owasp_breakdown")


def defense_gap_figure(tables_dir: Path, figures_dir: Path) -> dict[str, object]:
    df = ordered_guardrail_frame(read_csv(tables_dir / "defense_gap_by_seed.csv"))
    fig, ax = plt.subplots(figsize=(10.2, 5.6))
    sns.violinplot(
        data=df,
        x="guardrail",
        y="defense_gap",
        hue="guardrail",
        order=GUARDRAIL_ORDER,
        hue_order=GUARDRAIL_ORDER,
        palette=PALETTE,
        legend=False,
        inner=None,
        cut=0,
        linewidth=0.7,
        ax=ax,
    )
    sns.boxplot(
        data=df,
        x="guardrail",
        y="defense_gap",
        order=GUARDRAIL_ORDER,
        width=0.22,
        showcaps=True,
        boxprops={"facecolor": "white", "edgecolor": "#1f2933", "linewidth": 1},
        whiskerprops={"color": "#1f2933", "linewidth": 1},
        medianprops={"color": "#1f2933", "linewidth": 1.2},
        showfliers=False,
        ax=ax,
    )
    ax.set_xticks(range(len(GUARDRAIL_ORDER)))
    ax.set_xticklabels([GUARDRAIL_LABELS.get(name, name) for name in GUARDRAIL_ORDER])
    ax.set_xlabel("")
    ax.set_ylabel("Defense gap per seed-SMR set")
    ax.set_ylim(-0.03, 1.03)
    ax.set_title("Distribution of Defense Gaps Across Seeds", weight="bold")
    return save_figure(fig, figures_dir, "defense_gap")


def transform_label(value: str) -> str:
    label = value.replace("translation_", "")
    label = label.replace("hex_utf8", "hex")
    label = label.replace("url_encode", "url")
    label = label.replace("html_entities", "html")
    label = label.replace("spaced_characters", "spaced")
    return label.replace("_", " ").title()


def transform_breakdown_table(raw_path: Path, variants_path: Path, paper_tables_dir: Path) -> pd.DataFrame:
    raw_rows, _duplicates = dedupe_results(load_jsonl(raw_path))
    variants = load_jsonl(variants_path)
    metadata = variant_metadata(variants, raw_rows)
    outcomes = pd.DataFrame(collapse_variant_outcomes(raw_rows, metadata))
    subset = outcomes[outcomes["smr"].isin(["SMR-2", "SMR-3"])].copy()
    subset["miss"] = ~subset["final_blocked"].astype(bool)
    summary = (
        subset.groupby(["smr", "transformation", "guardrail"], as_index=False)
        .agg(variant_outcomes=("variant_id", "count"), miss_rate=("miss", "mean"))
        .sort_values(["smr", "transformation", "guardrail"])
    )
    summary["transformation_label"] = summary["transformation"].map(transform_label)
    output = paper_tables_dir / "transform_breakdown.csv"
    output.parent.mkdir(parents=True, exist_ok=True)
    summary.to_csv(output, index=False)
    return summary


def transform_breakdown_figure(
    raw_path: Path,
    variants_path: Path,
    paper_tables_dir: Path,
    figures_dir: Path,
) -> dict[str, object]:
    df = transform_breakdown_table(raw_path, variants_path, paper_tables_dir)
    fig, axes = plt.subplots(2, 1, figsize=(12.5, 8.0), constrained_layout=True)
    for ax, smr, title in zip(
        axes,
        ["SMR-2", "SMR-3"],
        ["Translation miss rate by language", "Encoding/obfuscation miss rate by transform"],
    ):
        sub = df[df["smr"] == smr].copy()
        pivot = (
            sub.pivot(index="guardrail", columns="transformation_label", values="miss_rate")
            .reindex(index=GUARDRAIL_ORDER)
            .rename(index=GUARDRAIL_LABELS)
        )
        sns.heatmap(
            pivot,
            ax=ax,
            vmin=0,
            vmax=1,
            cmap="PuBuGn",
            linewidths=0.7,
            linecolor="white",
            annot=True,
            fmt=".2f",
            cbar_kws={"label": "allow/miss rate"},
        )
        ax.set_title(title, weight="bold")
        ax.set_xlabel("")
        ax.set_ylabel("")
    return save_figure(fig, figures_dir, "transform_breakdown")


def wedge_comparison_table(tables_dir: Path, paper_tables_dir: Path) -> pd.DataFrame:
    flat = read_csv(tables_dir / "flat_detection_summary.csv")
    msir = read_csv(tables_dir / "msir_by_guardrail.csv")
    flat_summary = (
        flat.groupby("guardrail", as_index=False)
        .apply(
            lambda frame: pd.Series(
                {
                    "variant_outcomes": frame["variant_outcomes"].sum(),
                    "blocked_outcomes": frame["blocked_outcomes"].sum(),
                }
            ),
            include_groups=False,
        )
        .reset_index(drop=True)
    )
    flat_summary["flat_block_rate"] = flat_summary["blocked_outcomes"] / flat_summary["variant_outcomes"]
    flat_summary["flat_miss_rate"] = 1.0 - flat_summary["flat_block_rate"]
    comparison = flat_summary.merge(msir[["guardrail", "mean", "ci95_low", "ci95_high"]], on="guardrail", how="left")
    comparison = comparison.rename(columns={"mean": "msir", "ci95_low": "msir_ci95_low", "ci95_high": "msir_ci95_high"})
    comparison["metric_gap_msir_minus_flat_miss"] = comparison["msir"] - comparison["flat_miss_rate"]
    comparison = ordered_guardrail_frame(comparison)
    output = paper_tables_dir / "wedge_comparison.csv"
    output.parent.mkdir(parents=True, exist_ok=True)
    comparison.to_csv(output, index=False)
    return comparison


def wedge_comparison_figure(tables_dir: Path, paper_tables_dir: Path, figures_dir: Path) -> dict[str, object]:
    df = wedge_comparison_table(tables_dir, paper_tables_dir)
    labels = [GUARDRAIL_LABELS.get(name, name) for name in df["guardrail"]]
    x = np.arange(len(df))
    width = 0.36
    fig, ax = plt.subplots(figsize=(10.2, 5.4))
    ax.bar(x - width / 2, df["flat_miss_rate"], width, label="Flat miss rate", color="#72b7b2", edgecolor="#2f3b4a")
    ax.bar(x + width / 2, df["msir"], width, label="Metamorphic inconsistency", color="#eeca3b", edgecolor="#2f3b4a")
    ax.set_xticks(x, labels)
    ax.set_ylabel("Rate")
    ax.set_ylim(0, 1)
    ax.set_title("Aggregate Detection vs Metamorphic Consistency Lens", weight="bold")
    ax.legend(frameon=True)
    ax.grid(axis="y", alpha=0.35)
    return save_figure(fig, figures_dir, "wedge_comparison")


def mitigation_figure(tables_dir: Path, mitigated_tables_dir: Path | None, paper_tables_dir: Path, figures_dir: Path) -> dict[str, object]:
    baseline = ordered_guardrail_frame(read_csv(tables_dir / "msir_by_guardrail.csv"))
    baseline = baseline[["guardrail", "mean"]].rename(columns={"mean": "baseline_msir"})
    if mitigated_tables_dir and (mitigated_tables_dir / "msir_by_guardrail.csv").exists():
        mitigated = read_csv(mitigated_tables_dir / "msir_by_guardrail.csv")[["guardrail", "mean"]]
        mitigation = baseline.merge(mitigated.rename(columns={"mean": "mitigated_msir"}), on="guardrail", how="left")
        status = "mitigated"
    else:
        mitigation = baseline.copy()
        mitigation["mitigated_msir"] = np.nan
        status = "mitigated_results_unavailable"
    mitigation["absolute_msir_drop"] = mitigation["baseline_msir"] - mitigation["mitigated_msir"]
    mitigation["relative_msir_drop"] = np.where(
        mitigation["baseline_msir"] > 0,
        mitigation["absolute_msir_drop"] / mitigation["baseline_msir"],
        np.nan,
    )
    mitigation["status"] = status
    mitigation_table = "mitigation.csv" if status == "mitigated" else "mitigation_unavailable.csv"
    mitigation.to_csv(paper_tables_dir / mitigation_table, index=False)

    x = np.arange(len(mitigation))
    width = 0.36
    fig, ax = plt.subplots(figsize=(9.8, 5.2))
    ax.bar(x - width / 2, mitigation["baseline_msir"], width, color="#4c78a8", edgecolor="#2f3b4a", label="Before")
    if mitigation["mitigated_msir"].notna().any():
        ax.bar(x + width / 2, mitigation["mitigated_msir"], width, color="#54a24b", edgecolor="#2f3b4a", label="After")
    else:
        ax.bar(
            x + width / 2,
            mitigation["baseline_msir"] * 0,
            width,
            color="white",
            edgecolor="#7a3b00",
            hatch="//",
            label="After (mitigated results unavailable)",
        )
        for idx in x:
            ax.text(idx + width / 2, 0.04, "unavailable", ha="center", va="bottom", rotation=90, fontsize=8, color="#7a3b00")
    ax.set_xticks(x, [GUARDRAIL_LABELS.get(name, name) for name in mitigation["guardrail"]])
    ax.set_ylim(0, max(0.5, float(mitigation["baseline_msir"].max()) + 0.12))
    ax.set_ylabel("MSIR")
    ax.set_title("Before/After Mitigation MSIR", weight="bold")
    ax.legend()
    return save_figure(fig, figures_dir, "mitigation")


def access_control_figure(paper_tables_dir: Path, figures_dir: Path) -> dict[str, object]:
    table_path = paper_tables_dir / "access_control_smoke.csv"
    png_path = figures_dir / "access_control_example.png"
    pdf_path = figures_dir / "access_control_example.pdf"
    make_example_figure(load_rows(table_path), "AC-001", png_path, pdf_path)
    return {
        "figure": "access_control_example",
        "png": str(png_path),
        "png_bytes": png_path.stat().st_size,
        "pdf": str(pdf_path),
        "pdf_bytes": pdf_path.stat().st_size,
    }


def verify_outputs(manifest: list[dict[str, object]]) -> None:
    from PIL import Image

    for row in manifest:
        png = Path(str(row["png"]))
        pdf = Path(str(row["pdf"]))
        if not png.exists() or png.stat().st_size <= 0:
            raise RuntimeError(f"Missing or empty PNG: {png}")
        if not pdf.exists() or pdf.stat().st_size <= 0:
            raise RuntimeError(f"Missing or empty PDF: {pdf}")
        with Image.open(png) as image:
            image.verify()
        if pdf.read_bytes()[:4] != b"%PDF":
            raise RuntimeError(f"Invalid PDF header: {pdf}")


def write_manifest(path: Path, manifest: list[dict[str, object]]) -> None:
    write_csv(path, manifest, ["figure", "png", "png_bytes", "pdf", "pdf_bytes"])


def parse_args() -> argparse.Namespace:
    parser = argparse.ArgumentParser(description="Generate Phase 7 paper figures.")
    parser.add_argument("--tables-dir", type=Path, default=RESULTS_DIR / "tables")
    parser.add_argument("--raw-results", type=Path, default=RAW_RESULTS_DIR / "results.jsonl")
    parser.add_argument("--variants", type=Path, default=VARIANT_DIR / "variants.jsonl")
    parser.add_argument("--paper-dir", type=Path, default=PAPER_DIR)
    parser.add_argument("--mitigated-tables-dir", type=Path, default=None)
    return parser.parse_args()


def main() -> None:
    args = parse_args()
    set_common_style()
    figures_dir = args.paper_dir / "figures"
    paper_tables_dir = args.paper_dir / "tables"
    figures_dir.mkdir(parents=True, exist_ok=True)
    paper_tables_dir.mkdir(parents=True, exist_ok=True)

    write_mermaid_sources(figures_dir)
    manifest = [
        architecture_figure(figures_dir),
        taxonomy_figure(figures_dir),
        msir_per_guardrail_figure(args.tables_dir, figures_dir),
        heatmap_figure(args.tables_dir, figures_dir),
        owasp_breakdown_figure(args.tables_dir, paper_tables_dir, figures_dir),
        defense_gap_figure(args.tables_dir, figures_dir),
        mitigation_figure(args.tables_dir, args.mitigated_tables_dir, paper_tables_dir, figures_dir),
        transform_breakdown_figure(args.raw_results, args.variants, paper_tables_dir, figures_dir),
        wedge_comparison_figure(args.tables_dir, paper_tables_dir, figures_dir),
        access_control_figure(paper_tables_dir, figures_dir),
    ]
    verify_outputs(manifest)
    write_manifest(paper_tables_dir / "phase7_figure_manifest.csv", manifest)
    print(json.dumps({"figures": len(manifest), "manifest": str(paper_tables_dir / "phase7_figure_manifest.csv")}, indent=2))


if __name__ == "__main__":
    main()
