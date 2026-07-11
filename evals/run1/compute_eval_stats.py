#!/usr/bin/env python3
"""
compute_eval_stats.py — RAG evaluation analytics & visualizations.

Reads eval_results.jsonl and produces:
  - Console statistics
  - PNG charts in eval_charts/

Usage:
    python compute_eval_stats.py
"""

import json
import os
from collections import defaultdict
from pathlib import Path

import matplotlib
matplotlib.use("Agg")
import matplotlib.pyplot as plt
import matplotlib.ticker as mticker
import numpy as np
import seaborn as sns

# ── Setup ─────────────────────────────────────────────────────────────
CHART_DIR = Path("eval_charts")
CHART_DIR.mkdir(exist_ok=True)

sns.set_theme(style="whitegrid", font_scale=1.1)
PALETTE = sns.color_palette("muted")
METRIC_COLORS = {"retrieval_relevance": "#4c72b0", "answer_correctness": "#dd8452",
                 "faithfulness": "#55a868", "citation_accuracy": "#c44e52"}
METRIC_SHORT = {"retrieval_relevance": "Retrieval", "answer_correctness": "Correctness",
                "faithfulness": "Faithfulness", "citation_accuracy": "Citation"}

results = []
with open("eval_results.jsonl", "r", encoding="utf-8") as f:
    for line in f:
        if line.strip():
            results.append(json.loads(line))

METRICS = list(METRIC_SHORT.keys())

def avg(vals):
    return sum(vals) / len(vals) if vals else 0

def get_vals(rs, metric):
    return [r["scores"].get(metric, 0) for r in rs
            if isinstance(r["scores"].get(metric, 0), (int, float))]

def save(fig, name):
    fig.savefig(CHART_DIR / f"{name}.png", dpi=150, bbox_inches="tight",
                facecolor="white")
    plt.close(fig)
    print(f"  -> {CHART_DIR}/{name}.png")


# ── Helpers ───────────────────────────────────────────────────────────

def group_by(field):
    groups = defaultdict(list)
    for r in results:
        groups[r.get(field, "unknown")].append(r)
    return dict(groups)

def manual_prefix(r):
    return "".join(c for c in r["question_id"] if c.isalpha())


# =====================================================================
#  CONSOLE STATS (kept from before)
# =====================================================================

print(f"Total questions: {len(results)}")
print("\n=== OVERALL ===")
for m in METRICS:
    vals = get_vals(results, m)
    print(f"  {METRIC_SHORT[m]:15s}: avg={avg(vals):.2f}  min={min(vals)}  max={max(vals)}  n={len(vals)}")

for label, field in [("QUESTION TYPE", "question_type"),
                     ("FAILURE MODE", "failure_mode_tested"),
                     ("DIFFICULTY", "difficulty")]:
    print(f"\n=== BY {label} ===")
    for cat, rs in sorted(group_by(field).items()):
        vals = {m: avg(get_vals(rs, m)) for m in METRICS}
        print(f"  {cat:30s} n={len(rs):3d}  ret={vals[METRICS[0]]:.2f}  "
              f"cor={vals[METRICS[1]]:.2f}  fai={vals[METRICS[2]]:.2f}  "
              f"cit={vals[METRICS[3]]:.2f}")

print("\n=== BY MANUAL ===")
by_manual = defaultdict(list)
for r in results:
    by_manual[manual_prefix(r)].append(r)
for m, rs in sorted(by_manual.items()):
    vals = {met: avg(get_vals(rs, met)) for met in METRICS}
    print(f"  {m:6s} n={len(rs):3d}  ret={vals[METRICS[0]]:.2f}  cor={vals[METRICS[1]]:.2f}  "
          f"fai={vals[METRICS[2]]:.2f}  cit={vals[METRICS[3]]:.2f}")

# Retrieval hit rate
hit = total_expected = 0
for r in results:
    for ec in r.get("expected_citations", []):
        total_expected += 1
        fp = ec.get("file_path", "")
        expected_file = fp.split("/")[-1] if fp else ""
        if expected_file and expected_file in [c["file_name"] for c in r.get("retrieved_chunks", [])]:
            hit += 1
print(f"\n  Citation hit rate: {hit}/{total_expected} ({100*hit/total_expected:.1f}%)")

# Refusal analysis
refusals = [r for r in results
            if "don't have enough" in r.get("generated_answer", "").lower()
            or "not enough information" in r.get("generated_answer", "").lower()]
correct_refusals = [r for r in refusals if not r.get("expected_citations", [])]
incorrect_refusals = [r for r in refusals if r.get("expected_citations", [])]
print(f"  Refusals: {len(refusals)} total  |  {len(correct_refusals)} correct  |  "
      f"{len(incorrect_refusals)} false ({100*len(incorrect_refusals)/max(len(refusals),1):.0f}% false-refusal rate)")

# Dedup
dup_counts = []
unique_counts = []
for r in results:
    files = [c["file_name"] for c in r.get("retrieved_chunks", [])]
    unique_counts.append(len(set(files)))
    dup_counts.append(len(files) - len(set(files)))
print(f"  Chunk dedup: avg {avg(dup_counts):.1f} dupes/query  |  avg {avg(unique_counts):.1f} unique docs/query")

# =====================================================================
#  CHART 1 — Overall score distribution (stacked, all 4 metrics)
# =====================================================================
print("\n=== GENERATING CHARTS ===")

fig, axes = plt.subplots(1, 4, figsize=(16, 4), sharey=True)
fig.suptitle("Score Distribution by Metric (1–5)", fontweight="bold", fontsize=14)
for ax, m in zip(axes, METRICS):
    vals = get_vals(results, m)
    counts = [vals.count(s) for s in range(1, 6)]
    colors = ["#e74c3c", "#e67e22", "#f1c40f", "#2ecc71", "#27ae60"]
    bars = ax.bar(range(1, 6), counts, color=colors, edgecolor="white", linewidth=0.5)
    ax.set_title(METRIC_SHORT[m], fontsize=12)
    ax.set_xlabel("Score")
    ax.set_xticks(range(1, 6))
    for bar, c in zip(bars, counts):
        if c > 0:
            ax.text(bar.get_x() + bar.get_width()/2, bar.get_height() + 1,
                    str(c), ha="center", va="bottom", fontsize=9)
axes[0].set_ylabel("# Questions")
fig.tight_layout(rect=[0, 0, 1, 0.93])
save(fig, "01_score_distributions")


# =====================================================================
#  CHART 2 — Correctness distribution by question type (stacked bars)
# =====================================================================

by_type = group_by("question_type")
type_order = sorted(by_type.keys(), key=lambda t: avg(get_vals(by_type[t], "answer_correctness")))

fig, ax = plt.subplots(figsize=(12, 6))
score_colors = {1: "#e74c3c", 2: "#e67e22", 3: "#f1c40f", 4: "#2ecc71", 5: "#27ae60"}
bottom = np.zeros(len(type_order))
for score in range(1, 6):
    widths = []
    for t in type_order:
        vals = get_vals(by_type[t], "answer_correctness")
        widths.append(100 * vals.count(score) / len(vals) if vals else 0)
    ax.barh(type_order, widths, left=bottom, color=score_colors[score],
            label=f"Score {score}", edgecolor="white", linewidth=0.5)
    bottom += np.array(widths)

ax.set_xlabel("% of Questions")
ax.set_title("Answer Correctness Distribution by Question Type", fontweight="bold")
ax.legend(loc="lower right", ncol=5, fontsize=9)
# Add count labels on right
for i, t in enumerate(type_order):
    n = len(by_type[t])
    ax.text(101, i, f"n={n}", va="center", fontsize=9, color="gray")
ax.set_xlim(0, 115)
save(fig, "02_correctness_by_question_type")


# =====================================================================
#  CHART 3 — Correctness distribution by failure mode (stacked bars)
# =====================================================================

by_fm = group_by("failure_mode_tested")
fm_order = sorted(by_fm.keys(), key=lambda t: avg(get_vals(by_fm[t], "answer_correctness")))

fig, ax = plt.subplots(figsize=(12, 7))
bottom = np.zeros(len(fm_order))
for score in range(1, 6):
    widths = []
    for fm in fm_order:
        vals = get_vals(by_fm[fm], "answer_correctness")
        widths.append(100 * vals.count(score) / len(vals) if vals else 0)
    ax.barh(fm_order, widths, left=bottom, color=score_colors[score],
            label=f"Score {score}", edgecolor="white", linewidth=0.5)
    bottom += np.array(widths)

ax.set_xlabel("% of Questions")
ax.set_title("Answer Correctness Distribution by Failure Mode", fontweight="bold")
ax.legend(loc="lower right", ncol=5, fontsize=9)
for i, fm in enumerate(fm_order):
    n = len(by_fm[fm])
    ax.text(101, i, f"n={n}", va="center", fontsize=9, color="gray")
ax.set_xlim(0, 115)
save(fig, "03_correctness_by_failure_mode")


# =====================================================================
#  CHART 4 — Heatmap: avg scores by question type × metric
# =====================================================================

types_sorted = sorted(by_type.keys(),
                      key=lambda t: avg(get_vals(by_type[t], "answer_correctness")),
                      reverse=True)
heat_data = np.array([[avg(get_vals(by_type[t], m)) for m in METRICS] for t in types_sorted])

fig, ax = plt.subplots(figsize=(8, 6))
im = ax.imshow(heat_data, cmap="RdYlGn", vmin=1, vmax=5, aspect="auto")
ax.set_xticks(range(len(METRICS)))
ax.set_xticklabels([METRIC_SHORT[m] for m in METRICS], fontsize=10)
ax.set_yticks(range(len(types_sorted)))
ax.set_yticklabels(types_sorted, fontsize=10)
for i in range(len(types_sorted)):
    for j in range(len(METRICS)):
        ax.text(j, i, f"{heat_data[i, j]:.1f}", ha="center", va="center",
                fontsize=10, fontweight="bold",
                color="white" if heat_data[i, j] < 2.5 else "black")
fig.colorbar(im, ax=ax, shrink=0.8, label="Avg Score (1–5)")
ax.set_title("Average Scores: Question Type × Metric", fontweight="bold")
save(fig, "04_heatmap_type_x_metric")


# =====================================================================
#  CHART 5 — Heatmap: avg scores by failure mode × metric
# =====================================================================

fms_sorted = sorted(by_fm.keys(),
                    key=lambda t: avg(get_vals(by_fm[t], "answer_correctness")),
                    reverse=True)
heat_fm = np.array([[avg(get_vals(by_fm[f], m)) for m in METRICS] for f in fms_sorted])

fig, ax = plt.subplots(figsize=(8, 7))
im = ax.imshow(heat_fm, cmap="RdYlGn", vmin=1, vmax=5, aspect="auto")
ax.set_xticks(range(len(METRICS)))
ax.set_xticklabels([METRIC_SHORT[m] for m in METRICS], fontsize=10)
ax.set_yticks(range(len(fms_sorted)))
ax.set_yticklabels(fms_sorted, fontsize=10)
for i in range(len(fms_sorted)):
    for j in range(len(METRICS)):
        ax.text(j, i, f"{heat_fm[i, j]:.1f}", ha="center", va="center",
                fontsize=9, fontweight="bold",
                color="white" if heat_fm[i, j] < 2.5 else "black")
fig.colorbar(im, ax=ax, shrink=0.8, label="Avg Score (1–5)")
ax.set_title("Average Scores: Failure Mode × Metric", fontweight="bold")
save(fig, "05_heatmap_failuremode_x_metric")


# =====================================================================
#  CHART 6 — Retrieval vs Correctness scatter (the RAG gap)
# =====================================================================

fig, ax = plt.subplots(figsize=(8, 6))
rets = [r["scores"]["retrieval_relevance"] for r in results]
cors = [r["scores"]["answer_correctness"] for r in results]
# Jitter for overlapping integer points
jitter = 0.12
rets_j = [v + np.random.uniform(-jitter, jitter) for v in rets]
cors_j = [v + np.random.uniform(-jitter, jitter) for v in cors]

# Color by question type bucket
type_buckets = {"cross-policy": "#e74c3c", "cross-manual": "#e67e22",
                "unanswerable": "#9b59b6"}
colors = [type_buckets.get(r.get("question_type", ""), "#3498db") for r in results]
alphas = [0.9 if r.get("question_type", "") in type_buckets else 0.4 for r in results]

for x, y, c, a in zip(rets_j, cors_j, colors, alphas):
    ax.scatter(x, y, c=c, alpha=a, s=30, edgecolors="none")

# Legend
from matplotlib.lines import Line2D
legend_elements = [
    Line2D([0], [0], marker="o", color="w", markerfacecolor="#3498db", markersize=8, label="Single-manual"),
    Line2D([0], [0], marker="o", color="w", markerfacecolor="#e74c3c", markersize=8, label="Cross-policy"),
    Line2D([0], [0], marker="o", color="w", markerfacecolor="#e67e22", markersize=8, label="Cross-manual"),
    Line2D([0], [0], marker="o", color="w", markerfacecolor="#9b59b6", markersize=8, label="Unanswerable"),
]
ax.legend(handles=legend_elements, loc="upper left", fontsize=9)

# Quadrant annotations
ax.axhline(y=3, color="gray", linestyle="--", alpha=0.3)
ax.axvline(x=3, color="gray", linestyle="--", alpha=0.3)
ax.text(1.3, 4.7, "Good retrieval\nbad answer\n(LLM problem)", fontsize=8, color="gray", ha="center")
ax.text(4.7, 1.3, "Good retrieval\nbad answer\n(FALSE NEGATIVES)", fontsize=8, color="#e74c3c",
        ha="center", fontweight="bold")
ax.set_xlabel("Retrieval Relevance")
ax.set_ylabel("Answer Correctness")
ax.set_title("Retrieval vs Correctness — The RAG Gap", fontweight="bold")
ax.set_xlim(0.5, 5.5)
ax.set_ylim(0.5, 5.5)
ax.set_xticks(range(1, 6))
ax.set_yticks(range(1, 6))
save(fig, "06_retrieval_vs_correctness_scatter")


# =====================================================================
#  CHART 7 — Pass/Fail rates by manual (stacked: 1, 2-3, 4-5)
# =====================================================================

fig, ax = plt.subplots(figsize=(10, 5))
manuals = sorted(by_manual.keys())
fail_pcts = []   # score 1
mid_pcts = []    # score 2-3
pass_pcts = []   # score 4-5
for m in manuals:
    vals = get_vals(by_manual[m], "answer_correctness")
    n = len(vals)
    fail_pcts.append(100 * sum(1 for v in vals if v <= 1) / n)
    mid_pcts.append(100 * sum(1 for v in vals if 2 <= v <= 3) / n)
    pass_pcts.append(100 * sum(1 for v in vals if v >= 4) / n)

x = np.arange(len(manuals))
w = 0.6
ax.bar(x, pass_pcts, w, label="Pass (4–5)", color="#27ae60")
ax.bar(x, mid_pcts, w, bottom=pass_pcts, label="Partial (2–3)", color="#f1c40f")
ax.bar(x, fail_pcts, w, bottom=[p+m for p, m in zip(pass_pcts, mid_pcts)],
       label="Fail (1)", color="#e74c3c")
ax.set_xticks(x)
ax.set_xticklabels(manuals)
ax.set_ylabel("% of Questions")
ax.set_title("Pass / Partial / Fail Rate by Manual", fontweight="bold")
ax.legend(loc="upper right")
# Add n= labels
for i, m in enumerate(manuals):
    ax.text(i, 102, f"n={len(by_manual[m])}", ha="center", fontsize=9, color="gray")
ax.set_ylim(0, 110)
save(fig, "07_pass_fail_by_manual")


# =====================================================================
#  CHART 8 — Chunk deduplication impact on correctness
# =====================================================================

fig, ax = plt.subplots(figsize=(8, 5))
unique_vs_corr = defaultdict(list)
for r in results:
    files = [c["file_name"] for c in r.get("retrieved_chunks", [])]
    n_unique = len(set(files))
    unique_vs_corr[n_unique].append(r["scores"]["answer_correctness"])

x_vals = sorted(unique_vs_corr.keys())
y_avgs = [avg(unique_vs_corr[x]) for x in x_vals]
y_counts = [len(unique_vs_corr[x]) for x in x_vals]

bars = ax.bar(x_vals, y_avgs, color="#3498db", edgecolor="white", width=0.7)
for bar, cnt in zip(bars, y_counts):
    ax.text(bar.get_x() + bar.get_width()/2, bar.get_height() + 0.05,
            f"n={cnt}", ha="center", fontsize=9, color="gray")
ax.set_xlabel("# Unique Source Documents in Top-10 Chunks")
ax.set_ylabel("Avg Answer Correctness")
ax.set_title("More Unique Documents → Better Answers", fontweight="bold")
ax.set_ylim(0, 5.5)
ax.axhline(y=avg(get_vals(results, "answer_correctness")), color="red",
           linestyle="--", alpha=0.5, label=f"Overall avg ({avg(get_vals(results, 'answer_correctness')):.2f})")
ax.legend()
save(fig, "08_unique_docs_vs_correctness")


# =====================================================================
#  CHART 9 — Refusal analysis: correct vs incorrect refusals
# =====================================================================

fig, axes = plt.subplots(1, 2, figsize=(12, 5))

# Left: refusal pie
answered = len(results) - len(refusals)
labels = [f"Answered\n({answered})", f"Correct refusal\n({len(correct_refusals)})",
          f"False refusal\n({len(incorrect_refusals)})"]
sizes = [answered, len(correct_refusals), len(incorrect_refusals)]
colors_pie = ["#27ae60", "#3498db", "#e74c3c"]
axes[0].pie(sizes, labels=labels, colors=colors_pie, autopct="%1.0f%%",
            startangle=90, textprops={"fontsize": 10})
axes[0].set_title("Response Behavior", fontweight="bold")

# Right: false refusals by question type
false_ref_types = defaultdict(int)
for r in incorrect_refusals:
    false_ref_types[r.get("question_type", "unknown")] += 1
fr_types = sorted(false_ref_types.keys(), key=lambda t: false_ref_types[t])
fr_counts = [false_ref_types[t] for t in fr_types]
axes[1].barh(fr_types, fr_counts, color="#e74c3c", edgecolor="white")
axes[1].set_xlabel("# False Refusals")
axes[1].set_title("False Refusals by Question Type", fontweight="bold")
for i, c in enumerate(fr_counts):
    axes[1].text(c + 0.3, i, str(c), va="center", fontsize=10)

fig.tight_layout()
save(fig, "09_refusal_analysis")


# =====================================================================
#  CHART 10 — Retrieval gap: where does the pipeline lose quality?
# =====================================================================

fig, ax = plt.subplots(figsize=(10, 5))
categories = sorted(by_type.keys(),
                    key=lambda t: avg(get_vals(by_type[t], "retrieval_relevance")),
                    reverse=True)
x = np.arange(len(categories))
w = 0.2

for i, m in enumerate(METRICS):
    vals = [avg(get_vals(by_type[t], m)) for t in categories]
    ax.bar(x + i*w, vals, w, label=METRIC_SHORT[m], color=METRIC_COLORS[m])

ax.set_xticks(x + 1.5*w)
ax.set_xticklabels(categories, rotation=30, ha="right", fontsize=9)
ax.set_ylabel("Avg Score (1–5)")
ax.set_title("RAG Pipeline Quality Drop: Retrieval → Correctness → Citation",
             fontweight="bold")
ax.legend(fontsize=9)
ax.set_ylim(0, 5.5)
ax.axhline(y=3, color="gray", linestyle="--", alpha=0.3)
save(fig, "10_pipeline_quality_drop")


# =====================================================================
#  CHART 11 — Faithfulness vs Correctness (hallucination quadrant)
# =====================================================================

fig, ax = plt.subplots(figsize=(7, 7))
faith = [r["scores"]["faithfulness"] for r in results]
corr = [r["scores"]["answer_correctness"] for r in results]
faith_j = [v + np.random.uniform(-jitter, jitter) for v in faith]
corr_j = [v + np.random.uniform(-jitter, jitter) for v in corr]

ax.scatter(faith_j, corr_j, alpha=0.4, s=25, c="#3498db", edgecolors="none")

# Quadrant labels
ax.axhline(y=3, color="gray", linestyle="--", alpha=0.3)
ax.axvline(x=3, color="gray", linestyle="--", alpha=0.3)
ax.text(1.5, 4.5, "Correct but\nhallucinated\n(DANGEROUS)", fontsize=9,
        ha="center", color="#e74c3c", fontweight="bold")
ax.text(4.5, 1.5, "Faithful but\nwrong\n(refusals)", fontsize=9,
        ha="center", color="#e67e22")
ax.text(4.5, 4.5, "GOOD", fontsize=12, ha="center", color="#27ae60", fontweight="bold")
ax.text(1.5, 1.5, "BAD", fontsize=12, ha="center", color="#e74c3c", fontweight="bold")

ax.set_xlabel("Faithfulness")
ax.set_ylabel("Answer Correctness")
ax.set_title("Faithfulness vs Correctness — Hallucination Risk Map", fontweight="bold")
ax.set_xlim(0.5, 5.5)
ax.set_ylim(0.5, 5.5)
ax.set_xticks(range(1, 6))
ax.set_yticks(range(1, 6))
save(fig, "11_faithfulness_vs_correctness")


# =====================================================================
#  CHART 12 — Difficulty impact (grouped bar)
# =====================================================================

fig, ax = plt.subplots(figsize=(8, 5))
by_diff = group_by("difficulty")
diffs = ["easy", "medium", "hard"]
x = np.arange(len(diffs))
w = 0.18
for i, m in enumerate(METRICS):
    vals = [avg(get_vals(by_diff.get(d, []), m)) for d in diffs]
    ax.bar(x + i*w, vals, w, label=METRIC_SHORT[m], color=METRIC_COLORS[m])
ax.set_xticks(x + 1.5*w)
ax.set_xticklabels(diffs)
ax.set_ylabel("Avg Score (1–5)")
ax.set_title("Scores by Difficulty Level", fontweight="bold")
ax.legend(fontsize=9)
ax.set_ylim(0, 5.5)
save(fig, "12_scores_by_difficulty")


# =====================================================================
#  SUMMARY STATS FOR CONSOLE
# =====================================================================

print("\n=== KEY RAG METRICS ===")
n = len(results)
pass_rate = 100 * sum(1 for r in results if r["scores"]["answer_correctness"] >= 4) / n
fail_rate = 100 * sum(1 for r in results if r["scores"]["answer_correctness"] <= 1) / n
perfect = sum(1 for r in results if all(r["scores"].get(m, 0) == 5 for m in METRICS))
false_neg = sum(1 for r in results
                if r["scores"]["retrieval_relevance"] >= 4
                and r["scores"]["answer_correctness"] <= 1)
halluc = sum(1 for r in results if r["scores"]["faithfulness"] <= 2)

print(f"  Pass rate (correctness >= 4):     {pass_rate:.1f}%  ({int(pass_rate*n/100)}/{n})")
print(f"  Fail rate (correctness <= 1):     {fail_rate:.1f}%  ({int(fail_rate*n/100)}/{n})")
print(f"  Perfect 5/5/5/5:                  {perfect}/{n}")
print(f"  False negatives (ret>=4, cor<=1): {false_neg}")
print(f"  Hallucination risk (faith<=2):    {halluc}")
print(f"  False refusal rate:               {len(incorrect_refusals)}/{len(refusals)} "
      f"({100*len(incorrect_refusals)/max(len(refusals),1):.0f}%)")
print(f"  Avg unique docs per query:        {avg(unique_counts):.1f} (of 10)")
print(f"  Citation hit rate:                {hit}/{total_expected} ({100*hit/total_expected:.0f}%)")

# Cross-policy vs single-manual comparison
single = [r for r in results if manual_prefix(r) != "CROSS"]
cross = [r for r in results if manual_prefix(r) == "CROSS"]
print(f"\n  Single-manual correctness avg:    {avg(get_vals(single, 'answer_correctness')):.2f}  (n={len(single)})")
print(f"  Cross-policy correctness avg:     {avg(get_vals(cross, 'answer_correctness')):.2f}  (n={len(cross)})")
print(f"  Gap:                              {avg(get_vals(single, 'answer_correctness')) - avg(get_vals(cross, 'answer_correctness')):.2f} points")

print(f"\n  Charts saved to {CHART_DIR}/  ({len(list(CHART_DIR.glob('*.png')))} files)")
