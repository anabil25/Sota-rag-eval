#!/usr/bin/env python3
"""
compute_v2_stats.py — Compare Run 1 vs Run 2 eval results and generate report data.

Reads:
  - eval_results.jsonl (Run 1 baseline)
  - eval_results_v2.jsonl (Run 2 — re-run of sub-4 failures with fixes)

Produces:
  - Console stats with comparisons
  - Charts in eval_charts_v2/
"""

import json
from collections import defaultdict
from pathlib import Path

import matplotlib
matplotlib.use("Agg")
import matplotlib.pyplot as plt
import numpy as np
import seaborn as sns

# ── Setup ─────────────────────────────────────────────────────────────
CHART_DIR = Path("eval_charts_v2")
CHART_DIR.mkdir(exist_ok=True)
sns.set_theme(style="whitegrid", font_scale=1.1)

METRICS = ["retrieval_relevance", "answer_correctness", "faithfulness", "citation_accuracy"]
METRIC_SHORT = {"retrieval_relevance": "Retrieval", "answer_correctness": "Correctness",
                "faithfulness": "Faithfulness", "citation_accuracy": "Citation"}
METRIC_COLORS = {"retrieval_relevance": "#4c72b0", "answer_correctness": "#dd8452",
                 "faithfulness": "#55a868", "citation_accuracy": "#c44e52"}

def load(path):
    results = []
    with open(path, "r", encoding="utf-8") as f:
        for line in f:
            if line.strip():
                results.append(json.loads(line))
    return results

def avg(vals):
    return sum(vals) / len(vals) if vals else 0

def get_vals(rs, metric):
    return [r["scores"].get(metric, 0) for r in rs if isinstance(r["scores"].get(metric, 0), (int, float))]

def save(fig, name):
    fig.savefig(CHART_DIR / f"{name}.png", dpi=150, bbox_inches="tight", facecolor="white")
    plt.close(fig)
    print(f"  -> {CHART_DIR}/{name}.png")

def group_by(results, field):
    groups = defaultdict(list)
    for r in results:
        groups[r.get(field, "unknown")].append(r)
    return dict(groups)

def manual_prefix(r):
    return "".join(c for c in r["question_id"] if c.isalpha())


# ── Load data ─────────────────────────────────────────────────────────
v1_all = load("eval_results.jsonl")
v2 = load("eval_results_v2.jsonl")
v1_by_id = {r["question_id"]: r for r in v1_all}
v2_by_id = {r["question_id"]: r for r in v2}

# Build merged view: v2 results for re-run questions, v1 for the rest
merged = []
for r in v1_all:
    qid = r["question_id"]
    if qid in v2_by_id:
        merged.append(v2_by_id[qid])
    else:
        merged.append(r)

# Only the questions that were re-run (for head-to-head comparison)
v1_rerun = [v1_by_id[r["question_id"]] for r in v2 if r["question_id"] in v1_by_id]

print(f"Run 1 total: {len(v1_all)}")
print(f"Run 2 re-run: {len(v2)}")
print(f"Merged total: {len(merged)}")

# =====================================================================
#  HEAD-TO-HEAD: v1 vs v2 on the 87 re-run questions
# =====================================================================
print("\n" + "=" * 70)
print("HEAD-TO-HEAD COMPARISON (87 re-run questions only)")
print("=" * 70)

for m in METRICS:
    v1_vals = get_vals(v1_rerun, m)
    v2_vals = get_vals(v2, m)
    delta = avg(v2_vals) - avg(v1_vals)
    arrow = "▲" if delta > 0 else "▼" if delta < 0 else "="
    print(f"  {METRIC_SHORT[m]:15s}  v1={avg(v1_vals):.2f}  v2={avg(v2_vals):.2f}  {arrow} {delta:+.2f}")

# Score distribution comparison
print("\n  Correctness distribution (re-run questions):")
for score in range(1, 6):
    v1c = sum(1 for r in v1_rerun if r["scores"]["answer_correctness"] == score)
    v2c = sum(1 for r in v2 if r["scores"]["answer_correctness"] == score)
    delta = v2c - v1c
    print(f"    Score {score}: v1={v1c:3d}  v2={v2c:3d}  ({delta:+d})")

# =====================================================================
#  MERGED: overall stats with v2 improvements folded in
# =====================================================================
print("\n" + "=" * 70)
print("MERGED RESULTS (191 questions — v2 for re-run, v1 for rest)")
print("=" * 70)

for m in METRICS:
    v1_vals = get_vals(v1_all, m)
    mg_vals = get_vals(merged, m)
    delta = avg(mg_vals) - avg(v1_vals)
    arrow = "▲" if delta > 0 else "▼" if delta < 0 else "="
    print(f"  {METRIC_SHORT[m]:15s}  v1={avg(v1_vals):.2f}  merged={avg(mg_vals):.2f}  {arrow} {delta:+.2f}")

# Pass/fail rates
print("\n  Pass/Fail rates (merged 191):")
n = len(merged)
for label, predicate in [("Pass (4-5)", lambda r: r["scores"]["answer_correctness"] >= 4),
                          ("Partial (2-3)", lambda r: 2 <= r["scores"]["answer_correctness"] <= 3),
                          ("Fail (1)", lambda r: r["scores"]["answer_correctness"] == 1)]:
    v1c = sum(1 for r in v1_all if predicate(r))
    mc = sum(1 for r in merged if predicate(r))
    print(f"    {label:15s}  v1={v1c:3d} ({100*v1c/n:.0f}%)  merged={mc:3d} ({100*mc/n:.0f}%)")

# =====================================================================
#  MOVEMENT ANALYSIS: which questions improved, degraded, stayed
# =====================================================================
print("\n" + "=" * 70)
print("QUESTION-LEVEL MOVEMENT")
print("=" * 70)

improved = []
degraded = []
unchanged = []
for r2 in v2:
    qid = r2["question_id"]
    r1 = v1_by_id.get(qid)
    if not r1:
        continue
    s1 = r1["scores"]["answer_correctness"]
    s2 = r2["scores"]["answer_correctness"]
    if s2 > s1:
        improved.append((qid, s1, s2, r1.get("question_type", ""), r1.get("failure_mode_tested", "")))
    elif s2 < s1:
        degraded.append((qid, s1, s2, r1.get("question_type", ""), r1.get("failure_mode_tested", "")))
    else:
        unchanged.append((qid, s1, s2, r1.get("question_type", ""), r1.get("failure_mode_tested", "")))

print(f"  Improved: {len(improved)}  |  Unchanged: {len(unchanged)}  |  Degraded: {len(degraded)}")

print(f"\n  TOP IMPROVEMENTS (gained 2+ points):")
for qid, s1, s2, qt, fm in sorted(improved, key=lambda x: x[2]-x[1], reverse=True):
    if s2 - s1 >= 2:
        print(f"    {qid}: {s1}→{s2} (+{s2-s1})  type={qt}  mode={fm}")

print(f"\n  DEGRADATIONS:")
for qid, s1, s2, qt, fm in degraded:
    print(f"    {qid}: {s1}→{s2} ({s2-s1})  type={qt}  mode={fm}")

# =====================================================================
#  REMAINING FAILURES: what still scores < 4
# =====================================================================
print("\n" + "=" * 70)
print("REMAINING FAILURES (still < 4 after v2)")
print("=" * 70)

still_failing = [r for r in v2 if r["scores"]["answer_correctness"] < 4]
print(f"  Still failing: {len(still_failing)} of {len(v2)}")

print(f"\n  By question type:")
by_type = defaultdict(int)
for r in still_failing:
    by_type[r.get("question_type", "unknown")] += 1
for qt, c in sorted(by_type.items(), key=lambda x: -x[1]):
    print(f"    {qt:30s}  {c}")

print(f"\n  By failure mode:")
by_fm = defaultdict(int)
for r in still_failing:
    by_fm[r.get("failure_mode_tested", "unknown")] += 1
for fm, c in sorted(by_fm.items(), key=lambda x: -x[1]):
    print(f"    {fm:30s}  {c}")

print(f"\n  Score 1s remaining:")
for r in still_failing:
    if r["scores"]["answer_correctness"] == 1:
        print(f'    {r["question_id"]}: type={r.get("question_type","")} mode={r.get("failure_mode_tested","")}')

print(f"\n  Score 2s remaining:")
for r in still_failing:
    if r["scores"]["answer_correctness"] == 2:
        print(f'    {r["question_id"]}: type={r.get("question_type","")} mode={r.get("failure_mode_tested","")}')

# Refusal analysis on v2
refusals_v2 = [r for r in v2
               if "don't have enough" in r.get("generated_answer", "").lower()
               or "not enough information" in r.get("generated_answer", "").lower()]
correct_ref = [r for r in refusals_v2 if not r.get("expected_citations", [])]
incorrect_ref = [r for r in refusals_v2 if r.get("expected_citations", [])]
print(f"\n  Refusals in v2: {len(refusals_v2)} total  |  {len(correct_ref)} correct  |  {len(incorrect_ref)} false")

# Dedup analysis
dup_counts_v2 = []
unique_counts_v2 = []
for r in v2:
    files = [c["file_name"] for c in r.get("retrieved_chunks", [])]
    unique_counts_v2.append(len(set(files)))
    dup_counts_v2.append(len(files) - len(set(files)))
print(f"  Chunk dedup v2: avg {avg(dup_counts_v2):.1f} dupes/query  |  avg {avg(unique_counts_v2):.1f} unique docs/query")

# Reranker scores
reranker_scores = []
for r in v2:
    for c in r.get("retrieved_chunks", []):
        rs = c.get("reranker_score", 0)
        if rs > 0:
            reranker_scores.append(rs)
if reranker_scores:
    print(f"  Reranker scores: avg={avg(reranker_scores):.3f}  min={min(reranker_scores):.3f}  max={max(reranker_scores):.3f}")
    top1 = []
    for r in v2:
        rscores = [c.get("reranker_score", 0) for c in r.get("retrieved_chunks", [])]
        if rscores:
            top1.append(max(rscores))
    if top1:
        print(f"  Top-1 reranker per question: avg={avg(top1):.3f}  min={min(top1):.3f}  max={max(top1):.3f}")
        # Correlate with correctness
        high = [r for r in v2 if max(c.get("reranker_score", 0) for c in r.get("retrieved_chunks", [])) >= 2.5]
        low = [r for r in v2 if 0 < max(c.get("reranker_score", 0) for c in r.get("retrieved_chunks", [])) < 2.5]
        if high:
            print(f"  High reranker (>=2.5): n={len(high)} avg_corr={avg(get_vals(high,'answer_correctness')):.2f}")
        if low:
            print(f"  Low reranker (<2.5):  n={len(low)} avg_corr={avg(get_vals(low,'answer_correctness')):.2f}")

# =====================================================================
#  CHARTS
# =====================================================================
print("\n=== GENERATING CHARTS ===")

score_colors = {1: "#e74c3c", 2: "#e67e22", 3: "#f1c40f", 4: "#2ecc71", 5: "#27ae60"}

# CHART 1: Head-to-head bar comparison (v1 vs v2 averages on re-run questions)
fig, ax = plt.subplots(figsize=(10, 5))
x = np.arange(len(METRICS))
w = 0.35
v1_avgs = [avg(get_vals(v1_rerun, m)) for m in METRICS]
v2_avgs = [avg(get_vals(v2, m)) for m in METRICS]
bars1 = ax.bar(x - w/2, v1_avgs, w, label="Run 1 (baseline)", color="#e74c3c", alpha=0.8)
bars2 = ax.bar(x + w/2, v2_avgs, w, label="Run 2 (with fixes)", color="#27ae60", alpha=0.8)
ax.set_xticks(x)
ax.set_xticklabels([METRIC_SHORT[m] for m in METRICS])
ax.set_ylabel("Avg Score (1–5)")
ax.set_title("Run 1 vs Run 2: Average Scores on 87 Re-Run Questions", fontweight="bold")
ax.legend()
ax.set_ylim(0, 5.5)
for b1, b2 in zip(bars1, bars2):
    delta = b2.get_height() - b1.get_height()
    color = "#27ae60" if delta > 0 else "#e74c3c"
    ax.text(b2.get_x() + b2.get_width()/2, b2.get_height() + 0.1,
            f"{delta:+.2f}", ha="center", fontsize=10, fontweight="bold", color=color)
save(fig, "01_v1_vs_v2_averages")


# CHART 2: Correctness distribution comparison (side-by-side)
fig, axes = plt.subplots(1, 2, figsize=(14, 5), sharey=True)
fig.suptitle("Correctness Distribution: Run 1 vs Run 2 (87 re-run questions)", fontweight="bold")
for ax, data, title in [(axes[0], v1_rerun, "Run 1 (baseline)"),
                         (axes[1], v2, "Run 2 (with fixes)")]:
    vals = get_vals(data, "answer_correctness")
    counts = [vals.count(s) for s in range(1, 6)]
    colors = [score_colors[s] for s in range(1, 6)]
    bars = ax.bar(range(1, 6), counts, color=colors, edgecolor="white")
    ax.set_title(title, fontsize=12)
    ax.set_xlabel("Score")
    ax.set_xticks(range(1, 6))
    for bar, c in zip(bars, counts):
        if c > 0:
            ax.text(bar.get_x() + bar.get_width()/2, bar.get_height() + 0.5,
                    str(c), ha="center", fontsize=11, fontweight="bold")
axes[0].set_ylabel("# Questions")
save(fig, "02_correctness_distribution_comparison")


# CHART 3: Movement waterfall — how many improved/unchanged/degraded
fig, ax = plt.subplots(figsize=(8, 5))
categories = ["Improved", "Unchanged", "Degraded"]
counts = [len(improved), len(unchanged), len(degraded)]
colors = ["#27ae60", "#f1c40f", "#e74c3c"]
bars = ax.bar(categories, counts, color=colors, edgecolor="white", width=0.6)
for bar, c in zip(bars, counts):
    ax.text(bar.get_x() + bar.get_width()/2, bar.get_height() + 0.5,
            str(c), ha="center", fontsize=14, fontweight="bold")
ax.set_ylabel("# Questions")
ax.set_title("Question Movement: Run 1 → Run 2", fontweight="bold")
ax.set_ylim(0, max(counts) + 5)
save(fig, "03_movement_waterfall")


# CHART 4: Score transition heatmap (v1 score → v2 score)
transition = np.zeros((5, 5), dtype=int)
for r2 in v2:
    r1 = v1_by_id.get(r2["question_id"])
    if r1:
        s1 = r1["scores"]["answer_correctness"]
        s2 = r2["scores"]["answer_correctness"]
        transition[s1-1][s2-1] += 1

fig, ax = plt.subplots(figsize=(7, 6))
im = ax.imshow(transition, cmap="YlGnBu", aspect="auto")
ax.set_xticks(range(5))
ax.set_xticklabels(range(1, 6))
ax.set_yticks(range(5))
ax.set_yticklabels(range(1, 6))
ax.set_xlabel("Run 2 Score")
ax.set_ylabel("Run 1 Score")
for i in range(5):
    for j in range(5):
        color = "white" if transition[i][j] > 5 else "black"
        ax.text(j, i, str(transition[i][j]), ha="center", va="center",
                fontsize=12, fontweight="bold", color=color)
# Diagonal line
ax.plot([-0.5, 4.5], [-0.5, 4.5], color="red", linestyle="--", alpha=0.5, linewidth=2)
fig.colorbar(im, ax=ax, shrink=0.8, label="# Questions")
ax.set_title("Score Transition Matrix (Run 1 → Run 2)", fontweight="bold")
save(fig, "04_score_transition_matrix")


# CHART 5: Remaining failures by question type
fig, ax = plt.subplots(figsize=(10, 5))
still_by_type = defaultdict(lambda: {"pass": 0, "fail": 0})
for r in v2:
    qt = r.get("question_type", "unknown")
    if r["scores"]["answer_correctness"] >= 4:
        still_by_type[qt]["pass"] += 1
    else:
        still_by_type[qt]["fail"] += 1

types_sorted = sorted(still_by_type.keys(), key=lambda t: still_by_type[t]["fail"], reverse=True)
passes = [still_by_type[t]["pass"] for t in types_sorted]
fails = [still_by_type[t]["fail"] for t in types_sorted]

x = np.arange(len(types_sorted))
ax.bar(x, passes, 0.6, label="Pass (4–5)", color="#27ae60")
ax.bar(x, fails, 0.6, bottom=passes, label="Fail (<4)", color="#e74c3c")
ax.set_xticks(x)
ax.set_xticklabels(types_sorted, rotation=30, ha="right", fontsize=9)
ax.set_ylabel("# Questions")
ax.set_title("Run 2: Pass vs Fail by Question Type", fontweight="bold")
ax.legend()
save(fig, "05_v2_pass_fail_by_type")


# CHART 6: Improvement by failure mode
fig, ax = plt.subplots(figsize=(12, 6))
by_fm_v1 = defaultdict(list)
by_fm_v2 = defaultdict(list)
for r2 in v2:
    r1 = v1_by_id.get(r2["question_id"])
    if r1:
        fm = r1.get("failure_mode_tested", "unknown")
        by_fm_v1[fm].append(r1["scores"]["answer_correctness"])
        by_fm_v2[fm].append(r2["scores"]["answer_correctness"])

fms = sorted(by_fm_v1.keys(), key=lambda f: avg(by_fm_v2[f]) - avg(by_fm_v1[f]), reverse=True)
x = np.arange(len(fms))
w = 0.35
v1_fm_avgs = [avg(by_fm_v1[f]) for f in fms]
v2_fm_avgs = [avg(by_fm_v2[f]) for f in fms]
ax.bar(x - w/2, v1_fm_avgs, w, label="Run 1", color="#e74c3c", alpha=0.7)
ax.bar(x + w/2, v2_fm_avgs, w, label="Run 2", color="#27ae60", alpha=0.7)
ax.set_xticks(x)
ax.set_xticklabels(fms, rotation=35, ha="right", fontsize=9)
ax.set_ylabel("Avg Correctness")
ax.set_title("Correctness by Failure Mode: Run 1 vs Run 2", fontweight="bold")
ax.legend()
ax.set_ylim(0, 5.5)
ax.axhline(y=4, color="gray", linestyle="--", alpha=0.3)
save(fig, "06_failure_mode_improvement")


# CHART 7: Merged full-population score distribution
fig, axes = plt.subplots(1, 2, figsize=(14, 5), sharey=True)
fig.suptitle("Full Population Correctness: Original vs Merged (191 questions)", fontweight="bold")
for ax, data, title in [(axes[0], v1_all, "Run 1 (original)"),
                         (axes[1], merged, "Merged (Run 2 folded in)")]:
    vals = get_vals(data, "answer_correctness")
    counts = [vals.count(s) for s in range(1, 6)]
    colors = [score_colors[s] for s in range(1, 6)]
    bars = ax.bar(range(1, 6), counts, color=colors, edgecolor="white")
    ax.set_title(title, fontsize=12)
    ax.set_xlabel("Score")
    ax.set_xticks(range(1, 6))
    for bar, c in zip(bars, counts):
        if c > 0:
            ax.text(bar.get_x() + bar.get_width()/2, bar.get_height() + 1,
                    str(c), ha="center", fontsize=11, fontweight="bold")
axes[0].set_ylabel("# Questions")
save(fig, "07_merged_distribution_comparison")


# CHART 8: Reranker score vs correctness (if available)
if reranker_scores:
    fig, ax = plt.subplots(figsize=(8, 6))
    rr_vs_corr = defaultdict(list)
    for r in v2:
        top_rr = max((c.get("reranker_score", 0) for c in r.get("retrieved_chunks", [])), default=0)
        if top_rr > 0:
            bucket = int(top_rr)  # 0, 1, 2, 3
            rr_vs_corr[bucket].append(r["scores"]["answer_correctness"])
    buckets = sorted(rr_vs_corr.keys())
    avgs_corr = [avg(rr_vs_corr[b]) for b in buckets]
    counts_b = [len(rr_vs_corr[b]) for b in buckets]
    labels = [f"{b}-{b+1}" for b in buckets]
    bars = ax.bar(labels, avgs_corr, color="#3498db", edgecolor="white")
    for bar, cnt in zip(bars, counts_b):
        ax.text(bar.get_x() + bar.get_width()/2, bar.get_height() + 0.1,
                f"n={cnt}", ha="center", fontsize=9, color="gray")
    ax.set_xlabel("Top-1 Reranker Score Range")
    ax.set_ylabel("Avg Answer Correctness")
    ax.set_title("Reranker Confidence vs Answer Quality", fontweight="bold")
    ax.set_ylim(0, 5.5)
    ax.axhline(y=4, color="gray", linestyle="--", alpha=0.3)
    save(fig, "08_reranker_vs_correctness")


# =====================================================================
#  PRINT SUMMARY
# =====================================================================
print("\n" + "=" * 70)
print("RUN 2 SUMMARY")
print("=" * 70)

v2_pass = sum(1 for r in v2 if r["scores"]["answer_correctness"] >= 4)
v2_fail1 = sum(1 for r in v2 if r["scores"]["answer_correctness"] == 1)
v2_fail2 = sum(1 for r in v2 if r["scores"]["answer_correctness"] == 2)
mg_pass = sum(1 for r in merged if r["scores"]["answer_correctness"] >= 4)
mg_fail1 = sum(1 for r in merged if r["scores"]["answer_correctness"] == 1)

print(f"  Re-run questions: {len(v2)}")
print(f"  Now passing (4-5): {v2_pass} ({100*v2_pass/len(v2):.0f}%)")
print(f"  Still score 1: {v2_fail1}")
print(f"  Still score 2: {v2_fail2}")
print(f"  Improved: {len(improved)}  |  Unchanged: {len(unchanged)}  |  Degraded: {len(degraded)}")
print(f"\n  MERGED (191 questions):")
print(f"  Pass rate: {mg_pass}/{len(merged)} ({100*mg_pass/len(merged):.0f}%)")
print(f"  Score-1 count: {mg_fail1}")
print(f"  Overall correctness: v1={avg(get_vals(v1_all,'answer_correctness')):.2f} → merged={avg(get_vals(merged,'answer_correctness')):.2f}")

print(f"\n  Charts saved to {CHART_DIR}/")
