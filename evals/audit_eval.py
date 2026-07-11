import json

qs = []
with open("eval_questions.jsonl", "r", encoding="utf-8") as f:
    for line in f:
        if line.strip():
            qs.append(json.loads(line))

# Ground truth length distribution
gt_lens = [len(q["ground_truth"]) for q in qs]
print(f"Ground truth length: avg={sum(gt_lens)/len(gt_lens):.0f} chars, min={min(gt_lens)}, max={max(gt_lens)}")
print(f"  0-100 chars: {sum(1 for l in gt_lens if l <= 100)}")
print(f"  100-300 chars: {sum(1 for l in gt_lens if 100 < l <= 300)}")
print(f"  300-500 chars: {sum(1 for l in gt_lens if 300 < l <= 500)}")
print(f"  500+ chars: {sum(1 for l in gt_lens if l > 500)}")

# Empty or very short ground truths
print("\nEmpty/very short ground truths:")
for q in qs:
    if len(q.get("ground_truth", "")) < 10:
        print(f"  {q['question_id']}: type={q.get('question_type','')} GT='{q['ground_truth']}'")

# Unanswerable questions
unanswerable = [q for q in qs if q.get("question_type") == "unanswerable"]
print(f"\nUnanswerable questions ({len(unanswerable)}):")
for q in unanswerable:
    gt = q["ground_truth"]
    cites = q.get("citations", [])
    has_refuse = "not covered" in gt.lower() or "cannot be answered" in gt.lower()
    print(f"  {q['question_id']}: refuse_signal={'YES' if has_refuse else 'NO'} cites={len(cites)} GT_len={len(gt)}")
    if not has_refuse:
        print(f"    GT: {gt[:150]}")

# Cross-policy citation count
cross = [q for q in qs if q["question_id"].startswith("CROSS")]
print(f"\nCross-policy questions ({len(cross)}):")
cite_counts = [len(q.get("citations", [])) for q in cross]
print(f"  Citations per question: avg={sum(cite_counts)/len(cite_counts):.1f} min={min(cite_counts)} max={max(cite_counts)}")
for q in cross[:5]:
    cites = q.get("citations", [])
    manuals = set(c.get("manual", "") for c in cites)
    print(f"  {q['question_id']}: {len(cites)} citations from {len(manuals)} manuals: {manuals}")

# Check: does the judge see the actual chunks content or just file names?
print("\n\n=== JUDGE PROMPT ISSUES ===")
print("1. Judge sees chunk FILE NAMES only, not content")
print("   -> Judge can't verify if the answer is grounded in what was actually retrieved")
print("   -> Faithfulness score is based on guess, not evidence")

# Check: ground truth inconsistency for 'unanswerable' questions
print("\n2. Unanswerable ground truth inconsistency:")
for q in qs:
    if q.get("question_type") == "unanswerable":
        gt = q["ground_truth"]
        cites = q.get("citations", [])
        if cites:
            print(f"  WARNING: {q['question_id']} is 'unanswerable' but has {len(cites)} expected citations")
        if "not covered" not in gt.lower() and "cannot be answered" not in gt.lower() and gt.strip():
            print(f"  AMBIGUOUS: {q['question_id']} GT doesn't clearly say 'not answerable': {gt[:100]}")

# Check: score-2 gap in correctness
print("\n3. Score definitions create a 3-point gap:")
print("   5 = fully correct with all key details")
print("   3 = partially correct")
print("   1 = wrong or contradicts")
print("   -> No clear guidance for score 2 or 4")
print("   -> Judge jumps from 'partially correct' to 'wrong' with no middle ground")
print("   -> This explains the bimodal distribution (cluster at 1 and 3, gap at 2)")

# Check: does correctness penalize extra correct info?
print("\n4. Correctness scoring ambiguity:")
print("   'Does the generated answer match the ground truth?'")
print("   -> If answer includes EVERYTHING in ground truth PLUS correct extra info, is that 5 or 4?")
print("   -> Run 1 data shows judge penalizes 'extra correct info' to score 4")
print("   -> But Run 2 shows judge scores 'overly detailed' as 3")
print("   -> Inconsistent treatment of completeness vs conciseness")

# How many questions have ground truth that references specific manual scope
print("\n5. Scope ambiguity in unanswerable questions:")
scope_issues = 0
for q in qs:
    gt = q["ground_truth"]
    if ("not covered in the" in gt.lower() or "cannot be answered from" in gt.lower()):
        # But does the search actually pull from that manual? It searches ALL manuals
        scope_issues += 1
        if scope_issues <= 3:
            print(f"  {q['question_id']}: GT says not in specific manual, but search returns from all manuals")
            print(f"    GT: {gt[:150]}")
print(f"  Total scope-ambiguous questions: {scope_issues}")
