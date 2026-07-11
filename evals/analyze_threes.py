import json
from collections import defaultdict

def load(p):
    r = []
    with open(p, "r", encoding="utf-8") as f:
        for l in f:
            if l.strip():
                r.append(json.loads(l))
    return r

v3 = load("evals/run3/eval_results_v3.jsonl")
v1 = {r["question_id"]: r for r in load("evals/run1/eval_results.jsonl")}

threes = [r for r in v3 if r["scores"]["answer_correctness"] == 3]

print(f"Total score-3s in Run 3: {len(threes)}")
print(f"  Were score 3 in v1 too: {sum(1 for r in threes if v1.get(r['question_id'],{}).get('scores',{}).get('answer_correctness',0)==3)}")
print(f"  Were score 1 in v1 (improved): {sum(1 for r in threes if v1.get(r['question_id'],{}).get('scores',{}).get('answer_correctness',0)==1)}")
print(f"  Were score 4-5 in v1 (regressed): {sum(1 for r in threes if v1.get(r['question_id'],{}).get('scores',{}).get('answer_correctness',0)>=4)}")

# Analyze what the judge says about each score-3
patterns = defaultdict(list)
for r in threes:
    notes = r["scores"].get("judge_notes", "").lower()
    ret = r["scores"]["retrieval_relevance"]
    faith = r["scores"]["faithfulness"]
    cite = r["scores"]["citation_accuracy"]
    gt_len = len(r.get("ground_truth", ""))
    ans_len = len(r.get("generated_answer", ""))
    
    # Classify the judge's complaint
    if "miss" in notes and ("detail" in notes or "key" in notes or "specific" in notes):
        pattern = "MISSING_KEY_DETAILS"
    elif "miss" in notes and ("source" in notes or "policy" in notes or "chunk" in notes):
        pattern = "RETRIEVAL_GAP"
    elif "incorrect" in notes or "contradict" in notes or "wrong" in notes:
        pattern = "INCORRECT_CLAIM"
    elif "partial" in notes and ("program" in notes or "manual" in notes):
        pattern = "PARTIAL_CROSS_PROGRAM"
    elif "omit" in notes or "lack" in notes or "incomplete" in notes:
        pattern = "INCOMPLETE_ANSWER"
    elif ret <= 3:
        pattern = "LOW_RETRIEVAL"
    else:
        pattern = "OTHER"
    
    patterns[pattern].append(r)

print("\n=== SCORE-3 ROOT CAUSE PATTERNS ===")
for pat, rs in sorted(patterns.items(), key=lambda x: -len(x[1])):
    print(f"\n[{pat}] — {len(rs)} questions")
    
    # Aggregate metrics
    rets = [r["scores"]["retrieval_relevance"] for r in rs]
    faiths = [r["scores"]["faithfulness"] for r in rs]
    cites = [r["scores"]["citation_accuracy"] for r in rs]
    print(f"  Avg retrieval={sum(rets)/len(rets):.1f}  faith={sum(faiths)/len(faiths):.1f}  cite={sum(cites)/len(cites):.1f}")
    
    # By question type
    types = defaultdict(int)
    for r in rs:
        types[r.get("question_type", "?")] += 1
    print(f"  Types: {dict(types)}")
    
    # Show examples with judge notes
    for r in rs[:4]:
        qid = r["question_id"]
        qt = r.get("question_type", "")
        fm = r.get("failure_mode_tested", "")
        v1s = v1.get(qid, {}).get("scores", {}).get("answer_correctness", "?")
        notes = r["scores"].get("judge_notes", "")[:200]
        print(f"  {qid} [{qt}|{fm}] v1={v1s}->3")
        print(f"    Judge: {notes}")
    if len(rs) > 4:
        print(f"  ... and {len(rs)-4} more")

# Deep dive: what specific details are being missed?
print("\n\n=== WHAT DETAILS ARE BEING MISSED? ===")
print("(Comparing ground truth vs generated answer for MISSING_KEY_DETAILS pattern)\n")

for r in patterns.get("MISSING_KEY_DETAILS", [])[:8]:
    qid = r["question_id"]
    gt = r["ground_truth"]
    ans = r["generated_answer"]
    notes = r["scores"].get("judge_notes", "")
    
    # Find numbers/thresholds in GT that might be missing from answer
    import re
    gt_numbers = set(re.findall(r'\$[\d,]+|\d+[\s-](?:day|month|year|hour|week|percent|%)', gt.lower()))
    ans_numbers = set(re.findall(r'\$[\d,]+|\d+[\s-](?:day|month|year|hour|week|percent|%)', ans.lower()))
    missing_numbers = gt_numbers - ans_numbers
    
    print(f"{qid}: {r['question'][:80]}")
    print(f"  Judge says: {notes[:150]}")
    if missing_numbers:
        print(f"  Numbers in GT missing from answer: {missing_numbers}")
    print(f"  GT length={len(gt)}  Answer length={len(ans)}")
    print()

# Actionable analysis: which are fixable and how?
print("\n=== FIXABILITY ANALYSIS ===")
fixable = {"prompt_fix": [], "retrieval_fix": [], "judge_artifact": [], "hard_to_fix": []}

for r in threes:
    ret = r["scores"]["retrieval_relevance"]
    faith = r["scores"]["faithfulness"]
    notes = r["scores"].get("judge_notes", "").lower()
    qt = r.get("question_type", "")
    
    if ret >= 4 and faith >= 4:
        # Good retrieval, good faithfulness, but only score 3 = judge is being strict or answer missing details
        fixable["prompt_fix"].append(r)
    elif ret <= 3:
        fixable["retrieval_fix"].append(r)
    elif "incorrect" in notes or "contradict" in notes:
        fixable["hard_to_fix"].append(r)
    else:
        fixable["judge_artifact"].append(r)

print(f"  Prompt fix (ret>=4, faith>=4, just missing details): {len(fixable['prompt_fix'])}")
for r in fixable["prompt_fix"][:5]:
    print(f"    {r['question_id']} [{r.get('question_type','')}] - {r['scores'].get('judge_notes','')[:100]}")

print(f"\n  Retrieval fix (ret<=3, not finding right chunks): {len(fixable['retrieval_fix'])}")
for r in fixable["retrieval_fix"][:5]:
    print(f"    {r['question_id']} [{r.get('question_type','')}] - {r['scores'].get('judge_notes','')[:100]}")

print(f"\n  Judge artifact (mixed signals, may be scoring edge): {len(fixable['judge_artifact'])}")
for r in fixable["judge_artifact"][:5]:
    print(f"    {r['question_id']} [{r.get('question_type','')}] ret={r['scores']['retrieval_relevance']} faith={r['scores']['faithfulness']} - {r['scores'].get('judge_notes','')[:100]}")

print(f"\n  Hard to fix (incorrect claims despite good retrieval): {len(fixable['hard_to_fix'])}")
for r in fixable["hard_to_fix"][:5]:
    print(f"    {r['question_id']} [{r.get('question_type','')}] - {r['scores'].get('judge_notes','')[:100]}")

print(f"\n=== SUMMARY ===")
print(f"  Total score-3s: {len(threes)}")
print(f"  Prompt-fixable (add 'be exhaustive'): {len(fixable['prompt_fix'])} → could become 4-5")
print(f"  Retrieval-fixable (better search): {len(fixable['retrieval_fix'])} → need more/better chunks")
print(f"  Judge artifacts (scoring noise): {len(fixable['judge_artifact'])} → may resolve with judge tuning")
print(f"  Hard to fix (model errors): {len(fixable['hard_to_fix'])} → need architectural changes")
