import json
from collections import defaultdict

def load(p):
    r = []
    with open(p, "r", encoding="utf-8") as f:
        for l in f:
            if l.strip():
                r.append(json.loads(l))
    return r

v1 = {r["question_id"]: r for r in load("evals/run1/eval_results.jsonl")}
v3 = {r["question_id"]: r for r in load("evals/run3/eval_results_v3.jsonl")}

# Find all regressions
regressions = []
for qid, r3 in v3.items():
    r1 = v1.get(qid)
    if not r1:
        continue
    s1 = r1["scores"]["answer_correctness"]
    s3 = r3["scores"]["answer_correctness"]
    if s3 < s1:
        regressions.append({
            "qid": qid,
            "s1": s1,
            "s3": s3,
            "drop": s1 - s3,
            "type": r3.get("question_type", ""),
            "mode": r3.get("failure_mode_tested", ""),
            "question": r3["question"],
            "gt": r3["ground_truth"][:200],
            "v1_answer": r1.get("generated_answer", "")[:300],
            "v3_answer": r3.get("generated_answer", "")[:300],
            "v1_judge": r1["scores"].get("judge_notes", ""),
            "v3_judge": r3["scores"].get("judge_notes", ""),
            "v1_ret": r1["scores"].get("retrieval_relevance", 0),
            "v3_ret": r3["scores"].get("retrieval_relevance", 0),
            "v1_faith": r1["scores"].get("faithfulness", 0),
            "v3_faith": r3["scores"].get("faithfulness", 0),
            "v3_chunks": [c["file_name"] for c in r3.get("retrieved_chunks", [])],
            "v1_chunks": [c["file_name"] for c in r1.get("retrieved_chunks", [])],
            "v3_refused": "don't have enough" in r3.get("generated_answer", "").lower(),
            "v1_refused": "don't have enough" in r1.get("generated_answer", "").lower(),
        })

regressions.sort(key=lambda x: -x["drop"])

print(f"Total regressions: {len(regressions)}")
print(f"  Drop of 3: {sum(1 for r in regressions if r['drop']>=3)}")
print(f"  Drop of 2: {sum(1 for r in regressions if r['drop']==2)}")
print(f"  Drop of 1: {sum(1 for r in regressions if r['drop']==1)}")

# Categorize root causes
categories = defaultdict(list)
for r in regressions:
    if r["v3_refused"] and not r["v1_refused"]:
        categories["NEW_REFUSAL"].append(r)
    elif r["v3_ret"] < r["v1_ret"] - 1:
        categories["RETRIEVAL_DEGRADED"].append(r)
    elif r["v3_faith"] < r["v1_faith"] - 1:
        categories["FAITHFULNESS_DROP"].append(r)
    elif r["s1"] == 5 and r["s3"] >= 3:
        categories["JUDGE_RECALIBRATION"].append(r)
    elif r["s1"] == 5 and r["s3"] <= 2:
        categories["SEVERE_REGRESSION"].append(r)
    else:
        categories["OTHER"].append(r)

print("\n=== ROOT CAUSE CATEGORIES ===")
for cat, items in sorted(categories.items(), key=lambda x: -len(x[1])):
    print(f"\n[{cat}] ({len(items)} questions)")
    for r in items:
        print(f"  {r['qid']}: {r['s1']}->{r['s3']} ({-r['drop']}) [{r['type']}|{r['mode']}]")
        print(f"    Q: {r['question'][:90]}")
        print(f"    v1 judge: {r['v1_judge'][:120]}")
        print(f"    v3 judge: {r['v3_judge'][:120]}")
        if r["v3_refused"]:
            print(f"    ** V3 REFUSED (v1 did not) **")
        # Check if chunks changed
        v1_set = set(r["v1_chunks"])
        v3_set = set(r["v3_chunks"])
        lost = v1_set - v3_set
        gained = v3_set - v1_set
        if lost:
            print(f"    LOST chunks: {list(lost)[:3]}")
        if gained:
            print(f"    GAINED chunks: {list(gained)[:3]}")
        print()

# Summary of which pipeline component caused each regression
print("\n=== FIX ATTRIBUTION ===")
print(f"  NEW_REFUSAL (prompt issue):        {len(categories.get('NEW_REFUSAL',[]))}")
print(f"  RETRIEVAL_DEGRADED (RAG issue):    {len(categories.get('RETRIEVAL_DEGRADED',[]))}")
print(f"  FAITHFULNESS_DROP (answer quality): {len(categories.get('FAITHFULNESS_DROP',[]))}")
print(f"  JUDGE_RECALIBRATION (eval issue):  {len(categories.get('JUDGE_RECALIBRATION',[]))}")
print(f"  SEVERE_REGRESSION (investigate):   {len(categories.get('SEVERE_REGRESSION',[]))}")
print(f"  OTHER:                             {len(categories.get('OTHER',[]))}")
