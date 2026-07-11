#!/usr/bin/env python3
"""
compute_v3_stats.py — Full analysis of Run 3 vs Run 1 and Run 2.

Reads eval_results.jsonl (v1), eval_results_v2.jsonl (v2), eval_results_v3.jsonl (v3)
"""

import json
from collections import defaultdict
from pathlib import Path

import matplotlib
matplotlib.use("Agg")
import matplotlib.pyplot as plt
import numpy as np

CHART_DIR = Path("eval_charts_v3")
CHART_DIR.mkdir(exist_ok=True)

METRICS = ["retrieval_relevance", "answer_correctness", "faithfulness", "citation_accuracy"]
METRIC_SHORT = {"retrieval_relevance": "Retrieval", "answer_correctness": "Correctness",
                "faithfulness": "Faithfulness", "citation_accuracy": "Citation"}
score_colors = {1: "#e74c3c", 2: "#e67e22", 3: "#f1c40f", 4: "#2ecc71", 5: "#27ae60"}

def load(path):
    results = []
    with open(path, "r", encoding="utf-8") as f:
        for line in f:
            if line.strip():
                results.append(json.loads(line))
    return results

def avg(vals):
    return sum(vals) / len(vals) if vals else 0

def get_vals(rs, m):
    return [r["scores"].get(m, 0) for r in rs if isinstance(r["scores"].get(m, 0), (int, float))]

def save(fig, name):
    fig.savefig(CHART_DIR / f"{name}.png", dpi=150, bbox_inches="tight", facecolor="white")
    plt.close(fig)
    print(f"  -> {CHART_DIR}/{name}.png")

def group_by(results, field):
    g = defaultdict(list)
    for r in results:
        g[r.get(field, "unknown")].append(r)
    return dict(g)

def manual_prefix(r):
    return "".join(c for c in r["question_id"] if c.isalpha())


# ── Load ──────────────────────────────────────────────────────────────
v1 = load("eval_results.jsonl")
v3 = load("eval_results_v3.jsonl")
v1_by_id = {r["question_id"]: r for r in v1}

# Try to load v2 for 3-way comparison
v2_by_id = {}
if Path("eval_results_v2.jsonl").exists():
    for r in load("eval_results_v2.jsonl"):
        v2_by_id[r["question_id"]] = r

print(f"Run 1: {len(v1)} questions")
print(f"Run 3: {len(v3)} questions")

# =====================================================================
#  OVERALL COMPARISON
# =====================================================================
print("\n" + "=" * 70)
print("OVERALL: RUN 1 vs RUN 3")
print("=" * 70)
for m in METRICS:
    v1v = avg(get_vals(v1, m))
    v3v = avg(get_vals(v3, m))
    d = v3v - v1v
    arrow = "▲" if d > 0 else "▼" if d < 0 else "="
    print(f"  {METRIC_SHORT[m]:15s}  v1={v1v:.2f}  v3={v3v:.2f}  {arrow} {d:+.2f}")

# Distribution
print("\n  Correctness distribution:")
for s in range(1, 6):
    v1c = sum(1 for r in v1 if r["scores"]["answer_correctness"] == s)
    v3c = sum(1 for r in v3 if r["scores"]["answer_correctness"] == s)
    print(f"    Score {s}: v1={v1c:3d}  v3={v3c:3d}  ({v3c-v1c:+d})")

# Pass/fail
n = len(v3)
print(f"\n  Pass/fail:")
for label, pred in [("Pass (4-5)", lambda r: r["scores"]["answer_correctness"] >= 4),
                     ("Partial (2-3)", lambda r: 2 <= r["scores"]["answer_correctness"] <= 3),
                     ("Fail (1)", lambda r: r["scores"]["answer_correctness"] == 1)]:
    v1c = sum(1 for r in v1 if pred(r))
    v3c = sum(1 for r in v3 if pred(r))
    print(f"    {label:15s}  v1={v1c:3d} ({100*v1c/len(v1):.0f}%)  v3={v3c:3d} ({100*v3c/n:.0f}%)")

# =====================================================================
#  BY CATEGORY
# =====================================================================
for label, field in [("QUESTION TYPE", "question_type"), ("FAILURE MODE", "failure_mode_tested"),
                     ("MANUAL", None)]:
    print(f"\n{'='*70}\nBY {label}: RUN 1 vs RUN 3\n{'='*70}")
    if field:
        v1g = group_by(v1, field)
        v3g = group_by(v3, field)
    else:
        v1g = defaultdict(list)
        v3g = defaultdict(list)
        for r in v1: v1g[manual_prefix(r)].append(r)
        for r in v3: v3g[manual_prefix(r)].append(r)
    
    all_keys = sorted(set(list(v1g.keys()) + list(v3g.keys())))
    for k in all_keys:
        v1v = avg(get_vals(v1g.get(k, []), "answer_correctness"))
        v3v = avg(get_vals(v3g.get(k, []), "answer_correctness"))
        d = v3v - v1v
        n_k = len(v3g.get(k, []))
        arrow = "▲" if d > 0.1 else "▼" if d < -0.1 else "="
        print(f"  {k:30s} n={n_k:3d}  v1={v1v:.2f}  v3={v3v:.2f}  {arrow} {d:+.2f}")

# =====================================================================
#  MOVEMENT
# =====================================================================
print(f"\n{'='*70}\nQUESTION MOVEMENT: RUN 1 → RUN 3\n{'='*70}")
improved = degraded = same = 0
big_wins = []
big_losses = []
for r3 in v3:
    r1 = v1_by_id.get(r3["question_id"])
    if not r1: continue
    s1 = r1["scores"]["answer_correctness"]
    s3 = r3["scores"]["answer_correctness"]
    if s3 > s1: 
        improved += 1
        if s3 - s1 >= 2: big_wins.append((r3["question_id"], s1, s3, r3.get("question_type","")))
    elif s3 < s1:
        degraded += 1
        if s1 - s3 >= 2: big_losses.append((r3["question_id"], s1, s3, r3.get("question_type","")))
    else: same += 1

print(f"  Improved: {improved}  Same: {same}  Degraded: {degraded}")

if big_wins:
    print(f"\n  Big wins (+2 or more):")
    for qid, s1, s3, qt in sorted(big_wins, key=lambda x: x[2]-x[1], reverse=True)[:15]:
        print(f"    {qid}: {s1}→{s3} (+{s3-s1}) [{qt}]")

if big_losses:
    print(f"\n  Big losses (-2 or more):")
    for qid, s1, s3, qt in big_losses:
        print(f"    {qid}: {s1}→{s3} ({s3-s1}) [{qt}]")

# Remaining failures
print(f"\n{'='*70}\nREMAINING FAILURES IN RUN 3\n{'='*70}")
score1s = [r for r in v3 if r["scores"]["answer_correctness"] == 1]
score2s = [r for r in v3 if r["scores"]["answer_correctness"] == 2]
print(f"  Score 1: {len(score1s)}")
for r in score1s:
    print(f"    {r['question_id']}: [{r.get('question_type','')}|{r.get('failure_mode_tested','')}] {r['question'][:80]}")
print(f"  Score 2: {len(score2s)}")
for r in score2s:
    print(f"    {r['question_id']}: [{r.get('question_type','')}|{r.get('failure_mode_tested','')}] {r['question'][:80]}")

# Refusals
refusals = [r for r in v3 if "don't have enough" in r.get("generated_answer","").lower()
            or "not enough information" in r.get("generated_answer","").lower()]
correct_ref = [r for r in refusals if not r.get("expected_citations",[])]
false_ref = [r for r in refusals if r.get("expected_citations",[])]
print(f"\n  Refusals: {len(refusals)} total | {len(correct_ref)} correct | {len(false_ref)} false")

# Dedup
uniq = [len(set(c["file_name"] for c in r.get("retrieved_chunks",[]))) for r in v3]
print(f"  Avg unique docs/query: {avg(uniq):.1f}")

# Reranker
rr_all = []
for r in v3:
    for c in r.get("retrieved_chunks",[]):
        rs = c.get("reranker_score",0)
        if rs > 0: rr_all.append(rs)
if rr_all:
    top1 = [max(c.get("reranker_score",0) for c in r.get("retrieved_chunks",[])) for r in v3 if r.get("retrieved_chunks")]
    print(f"  Reranker: avg={avg(rr_all):.3f} top1_avg={avg(top1):.3f}")

# =====================================================================
#  CHARTS
# =====================================================================
print(f"\n=== GENERATING CHARTS ===")

# Chart 1: 3-run comparison bars
fig, ax = plt.subplots(figsize=(10, 5))
x = np.arange(len(METRICS))
w = 0.25
v1_avgs = [avg(get_vals(v1, m)) for m in METRICS]
v3_avgs = [avg(get_vals(v3, m)) for m in METRICS]
ax.bar(x - w, v1_avgs, w, label="Run 1 (baseline)", color="#e74c3c", alpha=0.8)
if v2_by_id:
    # Build merged v2
    v2_merged = []
    for r in v1:
        v2_merged.append(v2_by_id.get(r["question_id"], r))
    v2_avgs = [avg(get_vals(v2_merged, m)) for m in METRICS]
    ax.bar(x, v2_avgs, w, label="Run 2 (prompt+dedup)", color="#f39c12", alpha=0.8)
ax.bar(x + w, v3_avgs, w, label="Run 3 (full pipeline)", color="#27ae60", alpha=0.8)
ax.set_xticks(x)
ax.set_xticklabels([METRIC_SHORT[m] for m in METRICS])
ax.set_ylabel("Avg Score (1-5)")
ax.set_title("Score Progression: Run 1 → Run 3", fontweight="bold")
ax.legend()
ax.set_ylim(0, 5.5)
save(fig, "01_3run_comparison")

# Chart 2: Correctness distribution across runs
fig, axes = plt.subplots(1, 3 if v2_by_id else 2, figsize=(16, 5), sharey=True)
fig.suptitle("Correctness Distribution Across Runs", fontweight="bold")
datasets = [("Run 1", v1)]
if v2_by_id:
    datasets.append(("Run 2 (merged)", v2_merged))
datasets.append(("Run 3", v3))
for ax, (title, data) in zip(axes, datasets):
    vals = get_vals(data, "answer_correctness")
    counts = [vals.count(s) for s in range(1, 6)]
    bars = ax.bar(range(1, 6), counts, color=[score_colors[s] for s in range(1, 6)], edgecolor="white")
    ax.set_title(title)
    ax.set_xlabel("Score")
    ax.set_xticks(range(1, 6))
    for bar, c in zip(bars, counts):
        if c > 0:
            ax.text(bar.get_x()+bar.get_width()/2, bar.get_height()+1, str(c), ha="center", fontsize=10, fontweight="bold")
axes[0].set_ylabel("# Questions")
save(fig, "02_distribution_progression")

# Chart 3: Pass/Fail by manual - v1 vs v3 side by side
v1_man = defaultdict(list)
v3_man = defaultdict(list)
for r in v1: v1_man[manual_prefix(r)].append(r)
for r in v3: v3_man[manual_prefix(r)].append(r)
manuals = sorted(set(list(v1_man.keys()) + list(v3_man.keys())))

fig, axes = plt.subplots(1, 2, figsize=(16, 5), sharey=True)
fig.suptitle("Pass/Fail by Manual: Run 1 vs Run 3", fontweight="bold")
for ax, (title, data_man) in zip(axes, [("Run 1", v1_man), ("Run 3", v3_man)]):
    pass_pct = [100*sum(1 for r in data_man.get(m,[]) if r["scores"]["answer_correctness"]>=4)/max(len(data_man.get(m,[])),1) for m in manuals]
    part_pct = [100*sum(1 for r in data_man.get(m,[]) if 2<=r["scores"]["answer_correctness"]<=3)/max(len(data_man.get(m,[])),1) for m in manuals]
    fail_pct = [100*sum(1 for r in data_man.get(m,[]) if r["scores"]["answer_correctness"]<=1)/max(len(data_man.get(m,[])),1) for m in manuals]
    x = np.arange(len(manuals))
    ax.bar(x, pass_pct, 0.6, label="Pass (4-5)", color="#27ae60")
    ax.bar(x, part_pct, 0.6, bottom=pass_pct, label="Partial (2-3)", color="#f1c40f")
    ax.bar(x, fail_pct, 0.6, bottom=[p+m for p,m in zip(pass_pct,part_pct)], label="Fail (1)", color="#e74c3c")
    ax.set_xticks(x)
    ax.set_xticklabels(manuals)
    ax.set_title(title)
    ax.legend(fontsize=8)
axes[0].set_ylabel("% Questions")
save(fig, "03_pass_fail_by_manual_comparison")

# Chart 4: Score transition matrix v1 → v3
transition = np.zeros((5, 5), dtype=int)
for r3 in v3:
    r1 = v1_by_id.get(r3["question_id"])
    if r1:
        s1 = r1["scores"]["answer_correctness"]
        s3 = r3["scores"]["answer_correctness"]
        transition[s1-1][s3-1] += 1
fig, ax = plt.subplots(figsize=(7, 6))
im = ax.imshow(transition, cmap="YlGnBu", aspect="auto")
ax.set_xticks(range(5)); ax.set_xticklabels(range(1,6))
ax.set_yticks(range(5)); ax.set_yticklabels(range(1,6))
ax.set_xlabel("Run 3 Score"); ax.set_ylabel("Run 1 Score")
for i in range(5):
    for j in range(5):
        ax.text(j, i, str(transition[i][j]), ha="center", va="center", fontsize=12, fontweight="bold",
                color="white" if transition[i][j] > 5 else "black")
ax.plot([-0.5,4.5],[-0.5,4.5], color="red", linestyle="--", alpha=0.5, linewidth=2)
fig.colorbar(im, ax=ax, shrink=0.8)
ax.set_title("Score Transition: Run 1 → Run 3", fontweight="bold")
save(fig, "04_transition_matrix_v1_v3")

# Chart 5: By question type - grouped bars v1 vs v3
by_type_v1 = group_by(v1, "question_type")
by_type_v3 = group_by(v3, "question_type")
types = sorted(set(list(by_type_v1.keys()) + list(by_type_v3.keys())),
               key=lambda t: avg(get_vals(by_type_v3.get(t,[]), "answer_correctness")), reverse=True)
fig, ax = plt.subplots(figsize=(12, 6))
x = np.arange(len(types))
w = 0.35
v1_t = [avg(get_vals(by_type_v1.get(t,[]),"answer_correctness")) for t in types]
v3_t = [avg(get_vals(by_type_v3.get(t,[]),"answer_correctness")) for t in types]
ax.bar(x-w/2, v1_t, w, label="Run 1", color="#e74c3c", alpha=0.7)
ax.bar(x+w/2, v3_t, w, label="Run 3", color="#27ae60", alpha=0.7)
ax.set_xticks(x); ax.set_xticklabels(types, rotation=30, ha="right", fontsize=9)
ax.set_ylabel("Avg Correctness"); ax.set_title("Correctness by Question Type: Run 1 vs Run 3", fontweight="bold")
ax.legend(); ax.set_ylim(0, 5.5); ax.axhline(y=4, color="gray", linestyle="--", alpha=0.3)
save(fig, "05_type_comparison_v1_v3")

# Chart 6: Heatmap v3 type x metric
types_sorted = sorted(by_type_v3.keys(), key=lambda t: avg(get_vals(by_type_v3[t],"answer_correctness")), reverse=True)
heat = np.array([[avg(get_vals(by_type_v3[t], m)) for m in METRICS] for t in types_sorted])
fig, ax = plt.subplots(figsize=(8, 6))
im = ax.imshow(heat, cmap="RdYlGn", vmin=1, vmax=5, aspect="auto")
ax.set_xticks(range(len(METRICS))); ax.set_xticklabels([METRIC_SHORT[m] for m in METRICS])
ax.set_yticks(range(len(types_sorted))); ax.set_yticklabels(types_sorted)
for i in range(len(types_sorted)):
    for j in range(len(METRICS)):
        ax.text(j, i, f"{heat[i,j]:.1f}", ha="center", va="center", fontsize=10, fontweight="bold",
                color="white" if heat[i,j]<2.5 else "black")
fig.colorbar(im, ax=ax, shrink=0.8, label="Avg Score")
ax.set_title("Run 3: Question Type × Metric Heatmap", fontweight="bold")
save(fig, "06_v3_heatmap")

# ── Summary ───────────────────────────────────────────────────────────
print(f"\n{'='*70}")
print("RUN 3 SUMMARY")
print(f"{'='*70}")
n = len(v3)
pass_r = sum(1 for r in v3 if r["scores"]["answer_correctness"]>=4)
s1 = sum(1 for r in v3 if r["scores"]["answer_correctness"]==1)
s2 = sum(1 for r in v3 if r["scores"]["answer_correctness"]==2)
print(f"  Questions: {n}")
print(f"  Pass rate (4-5): {pass_r}/{n} ({100*pass_r/n:.0f}%)")
print(f"  Score 1: {s1}  Score 2: {s2}  Score 1+2: {s1+s2}")
print(f"  Correctness: v1={avg(get_vals(v1,'answer_correctness')):.2f} → v3={avg(get_vals(v3,'answer_correctness')):.2f}")
print(f"  Improved: {improved}  Same: {same}  Degraded: {degraded}")
print(f"  Charts saved to {CHART_DIR}/")
