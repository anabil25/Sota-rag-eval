import json
from collections import defaultdict

def load(p):
    r = []
    with open(p, "r", encoding="utf-8") as f:
        for l in f:
            if l.strip():
                r.append(json.loads(l))
    return r

def avg(v):
    return sum(v) / len(v) if v else 0

def gv(rs, m):
    return [r["scores"].get(m, 0) for r in rs if isinstance(r["scores"].get(m, 0), (int, float))]

def mp(r):
    return "".join(c for c in r["question_id"] if c.isalpha())

METRICS = ["retrieval_relevance", "answer_correctness", "faithfulness", "citation_accuracy"]
SHORT = {"retrieval_relevance": "Retrieval", "answer_correctness": "Correctness",
         "faithfulness": "Faithfulness", "citation_accuracy": "Citation"}

v1 = load("evals/run1/eval_results.jsonl")
v3 = load("evals/run3/eval_results_v3.jsonl")
v4 = load("evals/run4/eval_results_v4.jsonl")
v1id = {r["question_id"]: r for r in v1}
v3id = {r["question_id"]: r for r in v3}

print(f"v1={len(v1)}  v3={len(v3)}  v4={len(v4)}")

print("\n=== OVERALL: v1 → v3 → v4 ===")
for m in METRICS:
    a1 = avg(gv(v1, m)); a3 = avg(gv(v3, m)); a4 = avg(gv(v4, m))
    print(f"  {SHORT[m]:15s} v1={a1:.2f}  v3={a3:.2f}  v4={a4:.2f}  Δv1v4={a4-a1:+.2f}  Δv3v4={a4-a3:+.2f}")

print("\n=== DISTRIBUTION ===")
for s in range(1, 6):
    c1 = sum(1 for r in v1 if r["scores"]["answer_correctness"] == s)
    c3 = sum(1 for r in v3 if r["scores"]["answer_correctness"] == s)
    c4 = sum(1 for r in v4 if r["scores"]["answer_correctness"] == s)
    print(f"  Score {s}: v1={c1:3d}  v3={c3:3d}  v4={c4:3d}")

n = len(v4)
print("\n=== PASS/FAIL ===")
for lbl, pred in [("Pass(4-5)", lambda r: r["scores"]["answer_correctness"] >= 4),
                   ("Partial(2-3)", lambda r: 2 <= r["scores"]["answer_correctness"] <= 3),
                   ("Fail(1)", lambda r: r["scores"]["answer_correctness"] == 1)]:
    c1 = sum(1 for r in v1 if pred(r))
    c3 = sum(1 for r in v3 if pred(r))
    c4 = sum(1 for r in v4 if pred(r))
    print(f"  {lbl:12s}  v1={c1:3d}({100*c1//len(v1)}%)  v3={c3:3d}({100*c3//len(v3)}%)  v4={c4:3d}({100*c4//n}%)")

print("\n=== BY QUESTION TYPE ===")
t4 = defaultdict(list)
for r in v4: t4[r.get("question_type", "?")].append(r)
t1 = defaultdict(list)
for r in v1: t1[r.get("question_type", "?")].append(r)
t3 = defaultdict(list)
for r in v3: t3[r.get("question_type", "?")].append(r)
for t in sorted(t4, key=lambda x: avg(gv(t4.get(x, []), "answer_correctness")), reverse=True):
    a1 = avg(gv(t1.get(t, []), "answer_correctness"))
    a3 = avg(gv(t3.get(t, []), "answer_correctness"))
    a4 = avg(gv(t4[t], "answer_correctness"))
    print(f"  {t:30s} n={len(t4[t]):3d}  v1={a1:.2f}  v3={a3:.2f}  v4={a4:.2f}")

print("\n=== BY MANUAL ===")
m4 = defaultdict(list)
for r in v4: m4[mp(r)].append(r)
m1 = defaultdict(list)
for r in v1: m1[mp(r)].append(r)
m3 = defaultdict(list)
for r in v3: m3[mp(r)].append(r)
for m in sorted(m4):
    a1 = avg(gv(m1.get(m, []), "answer_correctness"))
    a3 = avg(gv(m3.get(m, []), "answer_correctness"))
    a4 = avg(gv(m4[m], "answer_correctness"))
    print(f"  {m:6s} n={len(m4[m]):3d}  v1={a1:.2f}  v3={a3:.2f}  v4={a4:.2f}")

# Movement v3→v4
print("\n=== MOVEMENT v3→v4 ===")
imp = deg = same = 0
for r4 in v4:
    r3 = v3id.get(r4["question_id"])
    if not r3: continue
    s3 = r3["scores"]["answer_correctness"]
    s4 = r4["scores"]["answer_correctness"]
    if s4 > s3: imp += 1
    elif s4 < s3: deg += 1
    else: same += 1
print(f"  Improved={imp}  Same={same}  Degraded={deg}")

# Movement v1→v4
print("\n=== MOVEMENT v1→v4 ===")
imp = deg = same = 0
for r4 in v4:
    r1 = v1id.get(r4["question_id"])
    if not r1: continue
    s1 = r1["scores"]["answer_correctness"]
    s4 = r4["scores"]["answer_correctness"]
    if s4 > s1: imp += 1
    elif s4 < s1: deg += 1
    else: same += 1
print(f"  Improved={imp}  Same={same}  Degraded={deg}")

# Remaining failures
print("\n=== REMAINING SCORE 1+2 ===")
s12 = [r for r in v4 if r["scores"]["answer_correctness"] <= 2]
print(f"  Total: {len(s12)}")
for r in s12:
    sc = r["scores"]["answer_correctness"]
    qt = r.get("question_type", "")
    fm = r.get("failure_mode_tested", "")
    print(f"  {r['question_id']}: score={sc} [{qt}|{fm}]")

# Refusals
ref = [r for r in v4 if "don't have enough" in r.get("generated_answer", "").lower()
       or "not enough information" in r.get("generated_answer", "").lower()]
cr = [r for r in ref if not r.get("expected_citations", [])]
fr = [r for r in ref if r.get("expected_citations", [])]
print(f"\n=== REFUSALS: total={len(ref)}  correct={len(cr)}  false={len(fr)} ===")

# Dedup
uniq = [len(set(c["file_name"] for c in r.get("retrieved_chunks", []))) for r in v4]
print(f"=== DEDUP: avg unique docs={avg(uniq):.1f} ===")

# V3 regressions fixed?
print("\n=== V3 REGRESSIONS STATUS ===")
v3_regs = ["APM015","SNAP017","SNAP022","MED027","APM007","APM011","APM022","APA026","MED014","MED024","TA005"]
for qid in v3_regs:
    r1 = v1id.get(qid, {}).get("scores", {}).get("answer_correctness", "?")
    r3 = v3id.get(qid, {}).get("scores", {}).get("answer_correctness", "?")
    r4v = [r for r in v4 if r["question_id"] == qid]
    r4 = r4v[0]["scores"]["answer_correctness"] if r4v else "?"
    fixed = "FIXED" if isinstance(r4, int) and isinstance(r1, int) and r4 >= r1 else "still regressed" if isinstance(r4, int) and isinstance(r1, int) and r4 < r1 else "?"
    print(f"  {qid}: v1={r1} v3={r3} v4={r4} {fixed}")
