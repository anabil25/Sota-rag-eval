import json
from collections import defaultdict

v2 = []
with open("eval_results_v2.jsonl", "r", encoding="utf-8") as f:
    for line in f:
        if line.strip():
            v2.append(json.loads(line))

v1_by_id = {}
with open("eval_results.jsonl", "r", encoding="utf-8") as f:
    for line in f:
        if line.strip():
            r = json.loads(line)
            v1_by_id[r["question_id"]] = r

def show(r, label):
    qid = r["question_id"]
    qt = r.get("question_type", "")
    fm = r.get("failure_mode_tested", "")
    q = r["question"][:120]
    gt = r["ground_truth"][:200]
    ans = r["generated_answer"][:250]
    notes = r["scores"].get("judge_notes", "")[:200]
    chunks = [c["file_name"] for c in r.get("retrieved_chunks", [])][:6]
    ret = r["scores"]["retrieval_relevance"]
    faith = r["scores"]["faithfulness"]
    cit = r["scores"]["citation_accuracy"]
    expected = [c.get("file_path", "").split("/")[-1] for c in r.get("expected_citations", [])]
    expected_found = [e for e in expected if e in [c["file_name"] for c in r.get("retrieved_chunks", [])]]

    print(f"\n{'='*80}")
    print(f"{label} | {qid} | type={qt} | mode={fm}")
    print(f"  ret={ret} faith={faith} cit={cit}")
    print(f"  Q: {q}")
    print(f"  GT: {gt}")
    print(f"  ANS: {ans}")
    print(f"  JUDGE: {notes}")
    print(f"  Expected sources: {expected} -> found: {expected_found}")
    print(f"  Top chunks: {chunks}")

print("=" * 80)
print("SCORE 1s IN RUN 2")
print("=" * 80)
for r in v2:
    if r["scores"]["answer_correctness"] == 1:
        show(r, "SCORE-1")

print("\n\n" + "=" * 80)
print("SCORE 2s IN RUN 2")
print("=" * 80)
for r in v2:
    if r["scores"]["answer_correctness"] == 2:
        show(r, "SCORE-2")

# Now analyze the 3s
print("\n\n" + "=" * 80)
print("SCORE 3 PATTERN ANALYSIS ({} questions)".format(
    sum(1 for r in v2 if r["scores"]["answer_correctness"] == 3)))
print("=" * 80)

threes = [r for r in v2 if r["scores"]["answer_correctness"] == 3]

# Group by root cause pattern
patterns = defaultdict(list)
for r in threes:
    gt = r["ground_truth"]
    ans = r["generated_answer"]
    notes = r["scores"].get("judge_notes", "").lower()
    ret = r["scores"]["retrieval_relevance"]
    faith = r["scores"]["faithfulness"]

    if "partial" in notes and ("multiple program" in notes or "cross" in notes or "program" in notes):
        patterns["Answered one program, missed the other(s)"].append(r)
    elif "omit" in notes or "miss" in notes or "lack" in notes or "incomplete" in notes:
        patterns["Partially correct but missing key details"].append(r)
    elif ret <= 3:
        patterns["Retrieval missed key sources"].append(r)
    elif faith <= 3 and ("halluc" in notes or "fabricat" in notes or "invent" in notes):
        patterns["Included fabricated/unsupported details"].append(r)
    elif "don't have enough" in ans.lower() or "not enough information" in ans.lower():
        patterns["Refused to answer (false refusal)"].append(r)
    else:
        patterns["Other (partial answer, mixed quality)"].append(r)

print(f"\nTotal score-3 questions: {len(threes)}")
print(f"\nRoot cause patterns:")
for pattern, rs in sorted(patterns.items(), key=lambda x: -len(x[1])):
    print(f"\n  [{len(rs):2d}] {pattern}")
    for r in rs[:3]:  # show first 3 examples
        qid = r["question_id"]
        qt = r.get("question_type", "")
        fm = r.get("failure_mode_tested", "")
        print(f"       {qid} [{qt}|{fm}] - {r['question'][:80]}")
    if len(rs) > 3:
        print(f"       ... and {len(rs)-3} more")

# Show a few full score-3 examples for the dominant pattern
print("\n\n" + "=" * 80)
print("SAMPLE SCORE-3 DEEP DIVES (first 5)")
print("=" * 80)
for r in threes[:5]:
    show(r, "SCORE-3")
