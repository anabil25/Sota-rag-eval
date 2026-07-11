#!/usr/bin/env python3
"""
compute_v4_stats.py — Full analysis of Run 4 vs Run 1 and Run 3.

Reads eval_results.jsonl (v1), eval_results_v3.jsonl (v3), eval_results_v4.jsonl (v4)
"""

import json
from collections import defaultdict
from pathlib import Path

import matplotlib
matplotlib.use("Agg")
import matplotlib.pyplot as plt
import numpy as np

CHART_DIR = Path("eval_charts_v4")
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
v1 = load("../run1/eval_results.jsonl")
v3 = load("../run3/eval_results_v3.jsonl")
v4 = load("eval_results_v4.jsonl")
v1_by_id = {r["question_id"]: r for r in v1}
v3_by_id = {r["question_id"]: r for r in v3}

print(f"Run 1: {len(v1)} questions")
print(f"Run 3: {len(v3)} questions")
print(f"Run 4: {len(v4)} questions")

# =====================================================================
#  OVERALL COMPARISON
# =====================================================================
print("\n" + "=" * 70)
print("OVERALL: RUN 1 vs RUN 3 vs RUN 4")
print("=" * 70)
for m in METRICS:
    v1v = avg(get_vals(v1, m))
    v3v = avg(get_vals(v3, m))
    v4v = avg(get_vals(v4, m))
    d14 = v4v - v1v
    d34 = v4v - v3v
    arrow = "▲" if d14 > 0 else "▼" if d14 < 0 else "="
    print(f"  {METRIC_SHORT[m]:15s}  v1={v1v:.2f}  v3={v3v:.2f}  v4={v4v:.2f}  {arrow} Δv1→v4={d14:+.2f}  Δv3→v4={d34:+.2f}")

# Distribution
print("\n  Correctness distribution:")
for s in range(1, 6):
    v1c = sum(1 for r in v1 if r["scores"]["answer_correctness"] == s)
    v3c = sum(1 for r in v3 if r["scores"]["answer_correctness"] == s)
    v4c = sum(1 for r in v4 if r["scores"]["answer_correctness"] == s)
    print(f"    Score {s}: v1={v1c:3d}  v3={v3c:3d}  v4={v4c:3d}  ({v4c-v1c:+d} from v1, {v4c-v3c:+d} from v3)")

# Pass/fail
n = len(v4)
print(f"\n  Pass/fail:")
for label, pred in [("Pass (4-5)", lambda r: r["scores"]["answer_correctness"] >= 4),
                     ("Partial (2-3)", lambda r: 2 <= r["scores"]["answer_correctness"] <= 3),
                     ("Fail (1)", lambda r: r["scores"]["answer_correctness"] == 1)]:
    v1c = sum(1 for r in v1 if pred(r))
    v3c = sum(1 for r in v3 if pred(r))
    v4c = sum(1 for r in v4 if pred(r))
    print(f"    {label:15s}  v1={v1c:3d} ({100*v1c/len(v1):.0f}%)  v3={v3c:3d} ({100*v3c/len(v3):.0f}%)  v4={v4c:3d} ({100*v4c/n:.0f}%)")

# =====================================================================
#  BY CATEGORY
# =====================================================================
for label, field in [("QUESTION TYPE", "question_type"), ("FAILURE MODE", "failure_mode_tested"),
                     ("MANUAL", None)]:
    print(f"\n{'='*70}\nBY {label}: RUN 1 vs RUN 3 vs RUN 4\n{'='*70}")
    if field:
        v1g = group_by(v1, field)
        v3g = group_by(v3, field)
        v4g = group_by(v4, field)
    else:
        v1g = defaultdict(list)
        v3g = defaultdict(list)
        v4g = defaultdict(list)
        for r in v1: v1g[manual_prefix(r)].append(r)
        for r in v3: v3g[manual_prefix(r)].append(r)
        for r in v4: v4g[manual_prefix(r)].append(r)
    
    all_keys = sorted(set(list(v1g.keys()) + list(v3g.keys()) + list(v4g.keys())))
    for k in all_keys:
        v1v = avg(get_vals(v1g.get(k, []), "answer_correctness"))
        v3v = avg(get_vals(v3g.get(k, []), "answer_correctness"))
        v4v = avg(get_vals(v4g.get(k, []), "answer_correctness"))
        d = v4v - v1v
        n_k = len(v4g.get(k, []))
        arrow = "▲" if d > 0.1 else "▼" if d < -0.1 else "="
        print(f"  {k:30s} n={n_k:3d}  v1={v1v:.2f}  v3={v3v:.2f}  v4={v4v:.2f}  {arrow} Δv1→v4={d:+.2f}")

# =====================================================================
#  MOVEMENT v3 → v4
# =====================================================================
print(f"\n{'='*70}\nQUESTION MOVEMENT: RUN 3 → RUN 4\n{'='*70}")
improved_34 = degraded_34 = same_34 = 0
big_wins_34 = []
big_losses_34 = []
for r4 in v4:
    r3 = v3_by_id.get(r4["question_id"])
    if not r3: continue
    s3 = r3["scores"]["answer_correctness"]
    s4 = r4["scores"]["answer_correctness"]
    if s4 > s3: 
        improved_34 += 1
        if s4 - s3 >= 2: big_wins_34.append((r4["question_id"], s3, s4, r4.get("question_type","")))
    elif s4 < s3:
        degraded_34 += 1
        if s3 - s4 >= 2: big_losses_34.append((r4["question_id"], s3, s4, r4.get("question_type","")))
    else: same_34 += 1

print(f"  Improved: {improved_34}  Same: {same_34}  Degraded: {degraded_34}")

if big_wins_34:
    print(f"\n  Big wins v3→v4 (+2 or more):")
    for qid, s3, s4, qt in sorted(big_wins_34, key=lambda x: x[2]-x[1], reverse=True)[:15]:
        print(f"    {qid}: {s3}→{s4} (+{s4-s3}) [{qt}]")

if big_losses_34:
    print(f"\n  Big losses v3→v4 (-2 or more):")
    for qid, s3, s4, qt in big_losses_34:
        print(f"    {qid}: {s3}→{s4} ({s4-s3}) [{qt}]")

# =====================================================================
#  MOVEMENT v1 → v4
# =====================================================================
print(f"\n{'='*70}\nQUESTION MOVEMENT: RUN 1 → RUN 4\n{'='*70}")
improved_14 = degraded_14 = same_14 = 0
big_wins_14 = []
big_losses_14 = []
for r4 in v4:
    r1 = v1_by_id.get(r4["question_id"])
    if not r1: continue
    s1 = r1["scores"]["answer_correctness"]
    s4 = r4["scores"]["answer_correctness"]
    if s4 > s1: 
        improved_14 += 1
        if s4 - s1 >= 2: big_wins_14.append((r4["question_id"], s1, s4, r4.get("question_type","")))
    elif s4 < s1:
        degraded_14 += 1
        if s1 - s4 >= 2: big_losses_14.append((r4["question_id"], s1, s4, r4.get("question_type","")))
    else: same_14 += 1

print(f"  Improved: {improved_14}  Same: {same_14}  Degraded: {degraded_14}")

if big_wins_14:
    print(f"\n  Big wins v1→v4 (+2 or more):")
    for qid, s1, s4, qt in sorted(big_wins_14, key=lambda x: x[2]-x[1], reverse=True)[:20]:
        print(f"    {qid}: {s1}→{s4} (+{s4-s1}) [{qt}]")

if big_losses_14:
    print(f"\n  Big losses v1→v4 (-2 or more):")
    for qid, s1, s4, qt in big_losses_14:
        print(f"    {qid}: {s1}→{s4} ({s4-s1}) [{qt}]")

# Remaining failures
print(f"\n{'='*70}\nREMAINING FAILURES IN RUN 4\n{'='*70}")
score1s = [r for r in v4 if r["scores"]["answer_correctness"] == 1]
score2s = [r for r in v4 if r["scores"]["answer_correctness"] == 2]
print(f"  Score 1: {len(score1s)}")
for r in score1s:
    r1s = v1_by_id.get(r["question_id"], {}).get("scores", {}).get("answer_correctness", "?")
    r3s = v3_by_id.get(r["question_id"], {}).get("scores", {}).get("answer_correctness", "?")
    print(f"    {r['question_id']}: v1={r1s} v3={r3s} v4=1 [{r.get('question_type','')}|{r.get('failure_mode_tested','')}] {r['question'][:80]}")
print(f"  Score 2: {len(score2s)}")
for r in score2s:
    r1s = v1_by_id.get(r["question_id"], {}).get("scores", {}).get("answer_correctness", "?")
    r3s = v3_by_id.get(r["question_id"], {}).get("scores", {}).get("answer_correctness", "?")
    print(f"    {r['question_id']}: v1={r1s} v3={r3s} v4=2 [{r.get('question_type','')}|{r.get('failure_mode_tested','')}] {r['question'][:80]}")

# Refusals
refusals = [r for r in v4 if "don't have enough" in r.get("generated_answer","").lower()
            or "not enough information" in r.get("generated_answer","").lower()]
correct_ref = [r for r in refusals if not r.get("expected_citations",[])]
false_ref = [r for r in refusals if r.get("expected_citations",[])]
print(f"\n  Refusals: {len(refusals)} total | {len(correct_ref)} correct | {len(false_ref)} false")

# Dedup
uniq = [len(set(c["file_name"] for c in r.get("retrieved_chunks",[]))) for r in v4]
print(f"  Avg unique docs/query: {avg(uniq):.1f}")

# Reranker
rr_all = []
for r in v4:
    for c in r.get("retrieved_chunks",[]):
        rs = c.get("reranker_score",0)
        if rs > 0: rr_all.append(rs)
if rr_all:
    top1 = [max(c.get("reranker_score",0) for c in r.get("retrieved_chunks",[])) for r in v4 if r.get("retrieved_chunks")]
    print(f"  Reranker: avg={avg(rr_all):.3f} top1_avg={avg(top1):.3f}")

# V3 regressions status
print(f"\n{'='*70}\nV3 REGRESSIONS STATUS IN V4\n{'='*70}")
v3_regs = ["APM015","SNAP017","SNAP022","MED027","APM007","APM011","APM022","APA026","MED014","MED024","TA005"]
for qid in v3_regs:
    r1s = v1_by_id.get(qid, {}).get("scores", {}).get("answer_correctness", "?")
    r3s = v3_by_id.get(qid, {}).get("scores", {}).get("answer_correctness", "?")
    r4v = [r for r in v4 if r["question_id"] == qid]
    r4s = r4v[0]["scores"]["answer_correctness"] if r4v else "?"
    if isinstance(r4s, int) and isinstance(r1s, int):
        status = "✓ FIXED" if r4s >= r1s else "↑ improved" if r4s > r3s else "still regressed"
    else:
        status = "?"
    print(f"  {qid}: v1={r1s} v3={r3s} v4={r4s}  {status}")

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
v4_avgs = [avg(get_vals(v4, m)) for m in METRICS]
ax.bar(x - w, v1_avgs, w, label="Run 1 (baseline)", color="#e74c3c", alpha=0.8)
ax.bar(x, v3_avgs, w, label="Run 3 (pipeline v2)", color="#f39c12", alpha=0.8)
ax.bar(x + w, v4_avgs, w, label="Run 4 (all fixes)", color="#27ae60", alpha=0.8)
ax.set_xticks(x)
ax.set_xticklabels([METRIC_SHORT[m] for m in METRICS])
ax.set_ylabel("Avg Score (1-5)")
ax.set_title("Score Progression: Run 1 → Run 3 → Run 4", fontweight="bold")
ax.legend()
ax.set_ylim(0, 5.5)
for i, (a1, a3, a4) in enumerate(zip(v1_avgs, v3_avgs, v4_avgs)):
    ax.text(i - w, a1 + 0.08, f"{a1:.2f}", ha="center", fontsize=8, fontweight="bold")
    ax.text(i, a3 + 0.08, f"{a3:.2f}", ha="center", fontsize=8, fontweight="bold")
    ax.text(i + w, a4 + 0.08, f"{a4:.2f}", ha="center", fontsize=8, fontweight="bold")
save(fig, "01_3run_comparison")

# Chart 2: Correctness distribution across runs
fig, axes = plt.subplots(1, 3, figsize=(16, 5), sharey=True)
fig.suptitle("Correctness Distribution Across Runs", fontweight="bold", fontsize=14)
for ax, (title, data) in zip(axes, [("Run 1 (baseline)", v1), ("Run 3 (pipeline v2)", v3), ("Run 4 (all fixes)", v4)]):
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

# Chart 3: Pass/Fail by manual - v1 vs v4 side by side
v1_man = defaultdict(list)
v3_man = defaultdict(list)
v4_man = defaultdict(list)
for r in v1: v1_man[manual_prefix(r)].append(r)
for r in v3: v3_man[manual_prefix(r)].append(r)
for r in v4: v4_man[manual_prefix(r)].append(r)
manuals = sorted(set(list(v1_man.keys()) + list(v4_man.keys())))

fig, axes = plt.subplots(1, 3, figsize=(20, 5), sharey=True)
fig.suptitle("Pass/Fail by Manual: Run 1 → Run 3 → Run 4", fontweight="bold")
for ax, (title, data_man) in zip(axes, [("Run 1", v1_man), ("Run 3", v3_man), ("Run 4", v4_man)]):
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

# Chart 4: Score transition matrix v1 → v4
fig, axes = plt.subplots(1, 2, figsize=(14, 6))
fig.suptitle("Score Transition Matrices", fontweight="bold")

for ax, (title, src, src_by_id) in zip(axes, [("Run 1 → Run 4", v1, v1_by_id), ("Run 3 → Run 4", v3, v3_by_id)]):
    transition = np.zeros((5, 5), dtype=int)
    for r4 in v4:
        rs = src_by_id.get(r4["question_id"])
        if rs:
            ss = rs["scores"]["answer_correctness"]
            s4 = r4["scores"]["answer_correctness"]
            transition[ss-1][s4-1] += 1
    im = ax.imshow(transition, cmap="YlGnBu", aspect="auto")
    ax.set_xticks(range(5)); ax.set_xticklabels(range(1,6))
    ax.set_yticks(range(5)); ax.set_yticklabels(range(1,6))
    ax.set_xlabel("Run 4 Score"); ax.set_ylabel(title.split(" →")[0] + " Score")
    for i in range(5):
        for j in range(5):
            ax.text(j, i, str(transition[i][j]), ha="center", va="center", fontsize=12, fontweight="bold",
                    color="white" if transition[i][j] > 5 else "black")
    ax.plot([-0.5,4.5],[-0.5,4.5], color="red", linestyle="--", alpha=0.5, linewidth=2)
    ax.set_title(title)
    fig.colorbar(im, ax=ax, shrink=0.8)
save(fig, "04_transition_matrices")

# Chart 5: By question type - grouped bars v1 vs v3 vs v4
by_type_v1 = group_by(v1, "question_type")
by_type_v3 = group_by(v3, "question_type")
by_type_v4 = group_by(v4, "question_type")
types = sorted(set(list(by_type_v1.keys()) + list(by_type_v4.keys())),
               key=lambda t: avg(get_vals(by_type_v4.get(t,[]), "answer_correctness")), reverse=True)
fig, ax = plt.subplots(figsize=(14, 6))
x = np.arange(len(types))
w = 0.25
v1_t = [avg(get_vals(by_type_v1.get(t,[]),"answer_correctness")) for t in types]
v3_t = [avg(get_vals(by_type_v3.get(t,[]),"answer_correctness")) for t in types]
v4_t = [avg(get_vals(by_type_v4.get(t,[]),"answer_correctness")) for t in types]
ax.bar(x-w, v1_t, w, label="Run 1", color="#e74c3c", alpha=0.7)
ax.bar(x, v3_t, w, label="Run 3", color="#f39c12", alpha=0.7)
ax.bar(x+w, v4_t, w, label="Run 4", color="#27ae60", alpha=0.7)
ax.set_xticks(x); ax.set_xticklabels(types, rotation=30, ha="right", fontsize=9)
ax.set_ylabel("Avg Correctness"); ax.set_title("Correctness by Question Type: Run 1 → Run 3 → Run 4", fontweight="bold")
ax.legend(); ax.set_ylim(0, 5.5); ax.axhline(y=4, color="gray", linestyle="--", alpha=0.3)
save(fig, "05_type_comparison")

# Chart 6: Heatmap v4 type x metric
types_sorted = sorted(by_type_v4.keys(), key=lambda t: avg(get_vals(by_type_v4[t],"answer_correctness")), reverse=True)
heat = np.array([[avg(get_vals(by_type_v4[t], m)) for m in METRICS] for t in types_sorted])
fig, ax = plt.subplots(figsize=(8, 6))
im = ax.imshow(heat, cmap="RdYlGn", vmin=1, vmax=5, aspect="auto")
ax.set_xticks(range(len(METRICS))); ax.set_xticklabels([METRIC_SHORT[m] for m in METRICS])
ax.set_yticks(range(len(types_sorted))); ax.set_yticklabels(types_sorted)
for i in range(len(types_sorted)):
    for j in range(len(METRICS)):
        ax.text(j, i, f"{heat[i,j]:.1f}", ha="center", va="center", fontsize=10, fontweight="bold",
                color="white" if heat[i,j]<2.5 else "black")
fig.colorbar(im, ax=ax, shrink=0.8, label="Avg Score")
ax.set_title("Run 4: Question Type × Metric Heatmap", fontweight="bold")
save(fig, "06_v4_heatmap")

# Chart 7: By failure mode - v1 vs v4
by_fm_v1 = group_by(v1, "failure_mode_tested")
by_fm_v3 = group_by(v3, "failure_mode_tested")
by_fm_v4 = group_by(v4, "failure_mode_tested")
fms = sorted(set(list(by_fm_v1.keys()) + list(by_fm_v4.keys())),
             key=lambda f: avg(get_vals(by_fm_v4.get(f,[]), "answer_correctness")), reverse=True)
fig, ax = plt.subplots(figsize=(14, 6))
x = np.arange(len(fms))
w = 0.25
v1_f = [avg(get_vals(by_fm_v1.get(f,[]),"answer_correctness")) for f in fms]
v3_f = [avg(get_vals(by_fm_v3.get(f,[]),"answer_correctness")) for f in fms]
v4_f = [avg(get_vals(by_fm_v4.get(f,[]),"answer_correctness")) for f in fms]
ax.bar(x-w, v1_f, w, label="Run 1", color="#e74c3c", alpha=0.7)
ax.bar(x, v3_f, w, label="Run 3", color="#f39c12", alpha=0.7)
ax.bar(x+w, v4_f, w, label="Run 4", color="#27ae60", alpha=0.7)
ax.set_xticks(x); ax.set_xticklabels(fms, rotation=35, ha="right", fontsize=8)
ax.set_ylabel("Avg Correctness"); ax.set_title("Correctness by Failure Mode: Run 1 → Run 3 → Run 4", fontweight="bold")
ax.legend(); ax.set_ylim(0, 5.5); ax.axhline(y=4, color="gray", linestyle="--", alpha=0.3)
save(fig, "07_failure_mode_comparison")

# Chart 8: Delta chart — improvement per question type v1→v4
deltas = [(t, avg(get_vals(by_type_v4.get(t,[]),"answer_correctness")) - avg(get_vals(by_type_v1.get(t,[]),"answer_correctness"))) for t in types]
deltas.sort(key=lambda x: x[1], reverse=True)
fig, ax = plt.subplots(figsize=(10, 6))
colors = ["#27ae60" if d >= 0 else "#e74c3c" for _, d in deltas]
ax.barh(range(len(deltas)), [d for _, d in deltas], color=colors, edgecolor="white")
ax.set_yticks(range(len(deltas))); ax.set_yticklabels([t for t, _ in deltas])
ax.set_xlabel("Δ Correctness (v1 → v4)")
ax.set_title("Improvement by Question Type: Run 1 → Run 4", fontweight="bold")
ax.axvline(x=0, color="black", linewidth=0.5)
for i, (_, d) in enumerate(deltas):
    ax.text(d + 0.02 if d >= 0 else d - 0.02, i, f"{d:+.2f}", va="center", ha="left" if d >= 0 else "right", fontsize=9)
save(fig, "08_delta_by_type")

# ── Summary ───────────────────────────────────────────────────────────
print(f"\n{'='*70}")
print("RUN 4 SUMMARY")
print(f"{'='*70}")
n = len(v4)
pass_r = sum(1 for r in v4 if r["scores"]["answer_correctness"]>=4)
s1 = sum(1 for r in v4 if r["scores"]["answer_correctness"]==1)
s2 = sum(1 for r in v4 if r["scores"]["answer_correctness"]==2)
s5 = sum(1 for r in v4 if r["scores"]["answer_correctness"]==5)
print(f"  Questions: {n}")
print(f"  Pass rate (4-5): {pass_r}/{n} ({100*pass_r/n:.0f}%)")
print(f"  Score 1: {s1}  Score 2: {s2}  Score 1+2: {s1+s2}  Score 5: {s5}")
print(f"  Correctness: v1={avg(get_vals(v1,'answer_correctness')):.2f} → v3={avg(get_vals(v3,'answer_correctness')):.2f} → v4={avg(get_vals(v4,'answer_correctness')):.2f}")
print(f"  Faithfulness: v1={avg(get_vals(v1,'faithfulness')):.2f} → v3={avg(get_vals(v3,'faithfulness')):.2f} → v4={avg(get_vals(v4,'faithfulness')):.2f}")
print(f"  v3→v4: Improved={improved_34}  Same={same_34}  Degraded={degraded_34}")
print(f"  v1→v4: Improved={improved_14}  Same={same_14}  Degraded={degraded_14}")
print(f"  False refusals: {len(false_ref)}")
print(f"  Charts saved to {CHART_DIR}/")
