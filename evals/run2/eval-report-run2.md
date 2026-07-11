# Alaska DPA Policy Search — Run 2 Evaluation Report

**Date:** April 1, 2026  
**Comparing:** Run 1 (baseline) vs Run 2 (prompt + RAG fixes applied)  
**Scope:** 87 questions that scored < 4 in Run 1, re-evaluated with all fixes  

---

## Changes Applied in Run 2

| Change | Component | Detail |
|---|---|---|
| **System prompt rewrite** | Prompt | Replaced generic prompt with production Policy Agent prompt + anti-refusal + cross-program + citation format + hallucination guardrail instructions |
| **Chunk deduplication** | RAG pipeline | Fetch top-20 from search, deduplicate by source file keeping highest reranker score, return 10 unique documents |
| **TOP_K 10 → 20** | RAG pipeline | Doubled raw retrieval to feed the deduplication step |
| **Manual field in context** | RAG pipeline | Each chunk now shows `[filename.md | Food Stamp Program]` so the model knows which program it comes from |
| **Synonym map expanded** | Search index | 24 → 35 entries: added prudent person, fee agent, deliverable fuel, collateral contact, in-kind support, shelter allowance, ratable reduction, job quit, drug felon, suspension |
| **Semantic config updated** | Search index | Added `manual` as a prioritized keyword field for the reranker |

---

## 1. Overall Impact

### Head-to-Head: 87 Re-Run Questions

| Metric | Run 1 | Run 2 | Delta |
|---|---|---|---|
| **Retrieval** | 3.89 | 4.06 | **+0.17** |
| **Correctness** | 2.01 | 3.07 | **+1.06** |
| **Faithfulness** | 2.51 | 3.47 | **+0.97** |
| **Citation** | 2.08 | 3.02 | **+0.94** |

Correctness improved by **+1.06 points** on re-run questions — from 2.01 (mostly failing) to 3.07 (partially correct).

### Correctness Distribution Shift

| Score | Run 1 | Run 2 | Change |
|---|---|---|---|
| 1 (critical failure) | 42 | **4** | **-38** |
| 2 (mostly wrong) | 2 | 8 | +6 |
| 3 (partially correct) | 43 | 56 | +13 |
| 4 (mostly correct) | 0 | **16** | **+16** |
| 5 (perfect) | 0 | **3** | **+3** |

The biggest win: **score-1 failures dropped from 42 to 4** (90% reduction). 19 questions now pass (score 4-5) that were all failing before.

### Merged Population (All 191 Questions)

| Metric | Run 1 | Merged | Delta |
|---|---|---|---|
| **Retrieval** | 4.29 | 4.37 | +0.08 |
| **Correctness** | 3.31 | **3.79** | **+0.48** |
| **Faithfulness** | 3.46 | 3.90 | +0.44 |
| **Citation** | 2.99 | 3.42 | +0.43 |

| Rate | Run 1 | Merged |
|---|---|---|
| **Pass (4-5)** | 104 (54%) | **123 (64%)** |
| **Partial (2-3)** | 45 (24%) | 64 (34%) |
| **Fail (1)** | 42 (22%) | **4 (2%)** |

**Pass rate: 54% → 64%. Failure rate: 22% → 2%.**

---

## 2. What the Fixes Actually Fixed

### 2.1 False Refusals: Eliminated

| Metric | Run 1 | Run 2 |
|---|---|---|
| Total refusals | 45 | 4 |
| False refusals | 38 (84%) | 4 (100%) |
| Avg unique docs per query | 6.0 | **9.4** |
| Avg duplicates per query | 3.9 | **0.0** |

The prompt rewrite and deduplication together crushed the refusal problem. Run 1 had 38 false refusals; Run 2 has 4. The dedup change is doing heavy lifting — avg 9.4 unique documents per query (up from 6.0) means the model gets much richer context.

### 2.2 Question Movement

| Direction | Count | % |
|---|---|---|
| **Improved** | 54 | 62% |
| Unchanged | 32 | 37% |
| Degraded | 1 | 1% |

**Only 1 degradation** (APM005: 3→2, a semantic-mismatch factual-lookup). 54 questions improved, with 34 gaining 2+ points.

### 2.3 Biggest Wins

| Question | Run 1 → Run 2 | Type | What Changed |
|---|---|---|---|
| TA019 (on strike + ATAP) | 1 → **5** | negation | Was refusing; now answers from retrieved chunk |
| TA004 (quit job + ATAP) | 1 → **4** | edge-case | Was refusing; prompt fix resolved |
| CROSS008 (GRA + SNAP + APA) | 1 → **4** | cross-policy | Dedup retrieved chunks from 3 programs |
| CROSS019 (notice content across programs) | 1 → **4** | cross-policy | Cross-program prompt instruction worked |
| APA005 (SSI payment standards) | 3 → **5** | factual-lookup | Better context from dedup |
| SNAP020 (ANCSA payments exempt) | 3 → **5** | negation | Synonym map helped retrieval |

---

## 3. What's Still Failing

### 3.1 The 4 Remaining Score-1s

| ID | Type | Failure Mode | Issue |
|---|---|---|---|
| APM023 | unanswerable | hallucination-bait | Still hallucinates SNAP allotment table despite guardrail prompt |
| MED003 | factual-lookup | table-extraction | Community spouse resource allowance — can't extract from retrieved table |
| CROSS011 | cross-policy | conflicting-rules | 16-year-old earnings: SNAP exempt vs ATAP countable — model gets the rules wrong |
| CROSS026 | cross-policy | conflicting-rules | IRA treatment across programs — conflates SNAP and APA rules |

### 3.2 The 8 Remaining Score-2s

| ID | Type | Failure Mode |
|---|---|---|
| APM005 | factual-lookup | semantic-mismatch |
| APM024 | unanswerable | hallucination-bait |
| APA019 | cross-manual | cross-document |
| CROSS001 | cross-policy | similar-programs |
| CROSS015 | cross-policy | cascading-eligibility |
| CROSS022 | cross-policy | multi-document-reasoning |
| CROSS033 | cross-policy | similar-programs |
| CROSS035 | cross-policy | program-interaction |

### 3.3 Remaining Failure Breakdown

68 questions still score < 4. The failure concentration:

| Category | Still Failing | % of Remaining Failures |
|---|---|---|
| **cross-policy** | 29 | 43% |
| **cross-manual** | 10 | 15% |
| **unanswerable** | 9 | 13% |
| All other types | 20 | 29% |

| Failure Mode | Still Failing | The Problem |
|---|---|---|
| **cross-document** (12) | Needs chunks from 2+ files simultaneously | Multi-query retrieval needed |
| **similar-programs** (10) | Model confuses which rule belongs to which program | Need program-specific sub-queries |
| **hallucination-bait** (9) | Model still fabricates on some unanswerable questions | Need stronger guardrails or post-generation validation |
| **conflicting-rules** (7) | Different programs have different rules for same concept | Multi-query + explicit program labels |
| **cascading-eligibility** (7) | "If X changes, what happens to programs A, B, C?" | Architecture limitation — needs reasoning chains |

---

## 4. Reranker Score Analysis (New Data)

Run 2 captured reranker scores for the first time:

| Metric | Value |
|---|---|
| Avg reranker score (all chunks) | 2.330 |
| Avg top-1 reranker per question | 2.686 |
| Min top-1 | 2.237 |
| Max top-1 | 3.254 |

| Reranker Bucket | Questions | Avg Correctness |
|---|---|---|
| High (top-1 ≥ 2.5) | 65 | 3.12 |
| Low (top-1 < 2.5) | 22 | 2.91 |

The reranker confidence correlates weakly with correctness (+0.21 difference). This suggests the reranker is doing its job finding relevant chunks, but the gap is in LLM synthesis — consistent with the overall finding that retrieval isn't the bottleneck.

---

## 5. What Worked and What Didn't

### What Worked (high ROI)

| Fix | Impact |
|---|---|
| **Anti-refusal prompt** | Eliminated 38 → 4 false refusals. Single biggest improvement. |
| **Chunk deduplication** | 6.0 → 9.4 unique docs/query. Zero duplicates. Gave model diverse multi-program context. |
| **Manual field in context** | Helped model attribute rules to correct programs for cross-manual questions. |
| **Synonym expansion** | Retrieved `100-1_prudent_person_concept.md` for APM018 (missed in Run 1). SNAP020 improved. |

### What Didn't Move the Needle Enough

| Fix | Why Limited |
|---|---|
| **Hallucination guardrail in prompt** | APM023 still fabricates tables. 9 hallucination-bait questions remain at score 3. Prompt-level guardrails aren't sufficient — needs a post-generation validation step. |
| **Cross-program prompt instruction** | Helped some (CROSS008, CROSS019 → 4) but 29 cross-policy questions still fail. The problem is retrieval breadth, not just prompt wording. |
| **Semantic config (manual in keywords)** | Marginal retrieval improvement (+0.17). The reranker was already doing OK. |

---

## 6. Next Steps: Priority Actions for Run 3

The low-hanging fruit has been picked. The remaining 68 failures require deeper architectural changes. These are the items that were deliberately excluded from Run 2 and should now be prioritized:

### 6.1 HIGH PRIORITY: Multi-Query Retrieval for Cross-Policy Questions

**Why now:** 29 cross-policy + 10 cross-manual = 39 of 68 remaining failures (57%). Single-query retrieval cannot solve these — the model needs chunks from 2-3 specific programs, but one query biases toward whichever program's terminology matches best.

**Implementation:**
1. Detect multi-program questions (keyword extraction: look for 2+ program names, or "compared to", "vs", "across programs")
2. Issue filtered queries per detected program: `$filter=manual eq 'Food Stamp Program'`
3. Take top-3 deduped chunks per program, merge into context
4. Label chunks by program in the context

**Expected impact:** +1.0 on the 39 cross-policy/cross-manual failures.

### 6.2 HIGH PRIORITY: Post-Generation Hallucination Validation

**Why now:** 9 hallucination-bait questions score 3 (partial), and 2 score 1-2. The prompt-level guardrail reduced severity but didn't eliminate fabrication.

**Implementation:**
1. After generating the answer, run a second LLM call: "Review this answer against the provided chunks. Flag any specific numbers, dollar amounts, or dates that do NOT appear verbatim in any chunk."
2. If flags are found, regenerate with explicit instruction to remove the flagged content.
3. Alternative: Use a structured output format that requires chunk-id citations per claim.

**Expected impact:** Eliminates the remaining hallucination failures (APM023, APM024 especially).

### 6.3 MEDIUM PRIORITY: BM25 Parameter Tuning

**Why now:** With reranker scores now captured, we can measure the impact. Current default k1/b may over-weight repeated policy terms.

**Implementation:** A/B test with k1=0.8, b=0.5 vs defaults. Run on the 12 cross-document failures to see if retrieval improves.

### 6.4 MEDIUM PRIORITY: HNSW m Parameter Increase (4 → 8)

**Why now:** 22 questions with low reranker scores (< 2.5) average 2.91 correctness. Better vector recall could surface more relevant chunks for edge-case queries.

**Implementation:** Requires index rebuild. Increase m from 4 to 8 for denser graph connections. Can be done during off-hours.

### 6.5 MEDIUM PRIORITY: Table-Aware Chunking

**Why now:** 2 table-extraction failures remain (MED003, TA011). Tables in policy documents get split across chunks, losing row/column structure.

**Implementation:** During ingestion, detect markdown tables and keep them intact within a single chunk even if it exceeds the normal chunk size limit.

### 6.6 LOW PRIORITY: Cascading Eligibility Reasoning

**Why now:** 7 cascading-eligibility failures require multi-step reasoning ("client loses job → affects ATAP → affects SNAP → affects Medicaid"). This is an architecture-level limitation.

**Implementation options:**
- Chain-of-thought prompting with explicit step-by-step program analysis
- Agent-based approach: run separate queries for each affected program, then synthesize
- This may require GraphRAG for relationship-aware retrieval

---

## 7. Run 2 Scorecard

| Metric | Run 1 | Run 2 (merged) | Target | Status |
|---|---|---|---|---|
| Overall correctness | 3.31 | **3.79** | 4.0+ | Getting closer |
| Pass rate (4-5) | 54% | **64%** | 80%+ | +10 points |
| Fail rate (1) | 22% | **2%** | 0% | Nearly there |
| Score 1+2 count | 44 | **12** | 0 | -73% |
| False refusal rate | 84% | ~100% (4 total) | 0% | Volume crushed, 4 remain |
| Unique docs/query | 6.0 | **9.4** | 10 | Solved |
| Cross-policy correctness | 1.83 | ~2.8 (est) | 4.0+ | Improved but still the weakest |

**Bottom line:** Run 2 validated that prompt engineering + dedup were the right first moves. Score-1 failures dropped 90%. But the remaining 68 sub-4 questions are structurally harder — they need multi-query retrieval (57% of remaining) and post-generation validation (13% of remaining), not more prompt tuning.
