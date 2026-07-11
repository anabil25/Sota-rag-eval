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
v1id = {r["question_id"]: r for r in v1}

v2id = {}
try:
    for r in load("evals/run2/eval_results_v2.jsonl"):
        v2id[r["question_id"]] = r
except:
    pass
v2_merged = [v2id.get(r["question_id"], r) for r in v1] if v2id else []

print(f"v1={len(v1)} v3={len(v3)}")

print("\n=== OVERALL ===")
for m in METRICS:
    v1v = avg(gv(v1, m))
    v3v = avg(gv(v3, m))
    v2v = avg(gv(v2_merged, m)) if v2_merged else 0
    d = v3v - v1v
    print(f"  {SHORT[m]:15s} v1={v1v:.2f}  v2m={v2v:.2f}  v3={v3v:.2f}  delta={d:+.2f}")

print("\n=== DISTRIBUTION ===")
for s in range(1, 6):
    c1 = sum(1 for r in v1 if r["scores"]["answer_correctness"] == s)
    c2 = sum(1 for r in v2_merged if r["scores"]["answer_correctness"] == s) if v2_merged else 0
    c3 = sum(1 for r in v3 if r["scores"]["answer_correctness"] == s)
    print(f"  Score {s}: v1={c1:3d}  v2m={c2:3d}  v3={c3:3d}")

n = len(v3)
print("\n=== PASS/FAIL ===")
for lbl, pred in [("Pass(4-5)", lambda r: r["scores"]["answer_correctness"] >= 4),
                   ("Partial(2-3)", lambda r: 2 <= r["scores"]["answer_correctness"] <= 3),
                   ("Fail(1)", lambda r: r["scores"]["answer_correctness"] == 1)]:
    c1 = sum(1 for r in v1 if pred(r))
    c3 = sum(1 for r in v3 if pred(r))
    print(f"  {lbl:12s}  v1={c1:3d}({100*c1//len(v1)}%)  v3={c3:3d}({100*c3//n}%)")

print("\n=== BY QUESTION TYPE ===")
t1 = defaultdict(list)
t3 = defaultdict(list)
for r in v1: t1[r.get("question_type", "?")].append(r)
for r in v3: t3[r.get("question_type", "?")].append(r)
for t in sorted(set(list(t1) + list(t3)),
                key=lambda x: avg(gv(t3.get(x, []), "answer_correctness")), reverse=True):
    v1a = avg(gv(t1.get(t, []), "answer_correctness"))
    v3a = avg(gv(t3.get(t, []), "answer_correctness"))
    print(f"  {t:30s} n={len(t3.get(t,[])):3d}  v1={v1a:.2f}  v3={v3a:.2f}  {v3a-v1a:+.2f}")

print("\n=== BY FAILURE MODE ===")
f1 = defaultdict(list)
f3 = defaultdict(list)
for r in v1: f1[r.get("failure_mode_tested", "?")].append(r)
for r in v3: f3[r.get("failure_mode_tested", "?")].append(r)
for fm in sorted(set(list(f1) + list(f3)),
                 key=lambda x: avg(gv(f3.get(x, []), "answer_correctness")), reverse=True):
    v1a = avg(gv(f1.get(fm, []), "answer_correctness"))
    v3a = avg(gv(f3.get(fm, []), "answer_correctness"))
    print(f"  {fm:30s} n={len(f3.get(fm,[])):3d}  v1={v1a:.2f}  v3={v3a:.2f}  {v3a-v1a:+.2f}")

print("\n=== BY MANUAL ===")
m1 = defaultdict(list)
m3 = defaultdict(list)
for r in v1: m1[mp(r)].append(r)
for r in v3: m3[mp(r)].append(r)
for m in sorted(m3):
    v1a = avg(gv(m1.get(m, []), "answer_correctness"))
    v3a = avg(gv(m3[m], "answer_correctness"))
    print(f"  {m:6s} n={len(m3[m]):3d}  v1={v1a:.2f}  v3={v3a:.2f}  {v3a-v1a:+.2f}")

print("\n=== MOVEMENT v1->v3 ===")
imp = deg = same = 0
bw = []
bl = []
for r3 in v3:
    r1 = v1id.get(r3["question_id"])
    if not r1:
        continue
    s1 = r1["scores"]["answer_correctness"]
    s3 = r3["scores"]["answer_correctness"]
    if s3 > s1:
        imp += 1
    elif s3 < s1:
        deg += 1
        bl.append((r3["question_id"], s1, s3, r3.get("question_type", "")))
    else:
        same += 1
    if s3 - s1 >= 2:
        bw.append((r3["question_id"], s1, s3, r3.get("question_type", "")))
print(f"  Improved={imp}  Same={same}  Degraded={deg}")
if bw:
    print("  Big wins (+2 or more):")
    for q, s1, s3, qt in sorted(bw, key=lambda x: x[2]-x[1], reverse=True)[:15]:
        print(f"    {q}: {s1}->{s3} (+{s3-s1}) [{qt}]")
if bl:
    print(f"  Degradations ({len(bl)}):")
    for q, s1, s3, qt in bl[:15]:
        print(f"    {q}: {s1}->{s3} ({s3-s1}) [{qt}]")

print("\n=== REMAINING SCORE 1+2 ===")
s12 = [r for r in v3 if r["scores"]["answer_correctness"] <= 2]
print(f"  Total: {len(s12)}")
for r in s12:
    sc = r["scores"]["answer_correctness"]
    qt = r.get("question_type", "")
    fm = r.get("failure_mode_tested", "")
    print(f"  {r['question_id']}: score={sc} [{qt}|{fm}] {r['question'][:70]}")

print("\n=== REFUSALS ===")
ref = [r for r in v3 if "don't have enough" in r.get("generated_answer", "").lower()
       or "not enough information" in r.get("generated_answer", "").lower()]
cr = [r for r in ref if not r.get("expected_citations", [])]
fr = [r for r in ref if r.get("expected_citations", [])]
print(f"  Total={len(ref)}  Correct={len(cr)}  False={len(fr)}")
for r in fr:
    print(f"    FALSE: {r['question_id']} [{r.get('question_type','')}]")

uniq = [len(set(c["file_name"] for c in r.get("retrieved_chunks", []))) for r in v3]
print(f"\n=== DEDUP: avg unique docs={avg(uniq):.1f} ===")

rr = [c.get("reranker_score", 0) for r in v3 for c in r.get("retrieved_chunks", []) if c.get("reranker_score", 0) > 0]
if rr:
    print(f"=== RERANKER: avg={avg(rr):.3f} ===")
