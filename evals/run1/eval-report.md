# Alaska DPA Policy Search — RAG Evaluation Report

**Date:** April 1, 2026  
**Index:** `policies-index` on `akpolicy2-search`  
**Model:** gpt-4o (answer generation + LLM-as-judge)  
**Search Mode:** Hybrid (BM25 + vector) with semantic reranking  
**Questions:** 191 across 8 policy manuals  

**Scoring:** All metrics use a 1–5 scale judged by gpt-4o: **1** = completely wrong / missing, **2** = mostly wrong, **3** = partially correct, **4** = mostly correct with minor gaps, **5** = fully correct and complete.

### Scoring Examples (Answer Correctness)

| Score | Example Question | What Happened | Why That Score |
|---|---|---|---|
| **5** | APM007: "What do I need to do if I get a subpoena about a client's case?" | Listed all steps: contact supervisor, email AG office (Justin Nelson), copy to DPA Director, wait for instructions, report even with a signed release | Every detail from the ground truth was present, correctly sourced |
| **4** | APM001: "What has to be included in a denial notice when someone is over the income limit?" | Got all key items (source, who received, calculation, conversion factor, effective date) but added an extra point about citing regulations not in ground truth | Mostly correct — all key details present, minor unsolicited addition |
| **3** | APA005: "What is the 2026 SSI payment standard for an individual living independently?" | Correctly stated $994 for independent living but omitted the B ($662.67) and D ($30) living arrangement standards | Partially correct — one of three expected values provided |
| **2** | APM024: "What are the income limits for Medicaid eligibility?" | Provided detailed dollar-amount tables from MAGI Medicaid chunks, but the ground truth says this info is "not covered in the APM" | Mostly wrong — question was about APM scope, not Medicaid numbers |
| **1** | APA010: "What happens to an APA case when someone temporarily loses eligibility?" | Said "I don't have enough information" despite retrieving `480-5_suspension_and_termination.md` which contains the answer | Complete failure — refused to answer with the right document in context |

---

## 1. Executive Summary

| Metric | Average (1–5) | Interpretation |
|---|---|---|
| **Retrieval Relevance** | **4.29** | Search finds the right documents most of the time |
| **Answer Correctness** | **3.31** | Answers are partially correct on average; 22% score 1/5 |
| **Faithfulness** | **3.46** | The LLM sometimes hallucinates or refuses when it has context |
| **Citation Accuracy** | **2.99** | Citation formatting is the weakest link |

**Bottom line:** Retrieval is solid for single-manual questions (avg 4.5+) but breaks down on cross-policy/cross-manual questions (avg 3.7). The biggest quality gap is not in search — it's in the LLM's ability to synthesize across multiple retrieved chunks from different manuals, and in its tendency to refuse answering (38 incorrect refusals vs. 7 correct refusals).

### Answer Correctness Distribution

| Score | Count | % |
|---|---|---|
| 5 (perfect) | 41 | 21.5% |
| 4 (mostly correct) | 63 | 33.0% |
| 3 (partially correct) | 43 | 22.5% |
| 2 (mostly wrong) | 2 | 1.0% |
| 1 (critical failure) | 42 | 22.0% |

27 questions achieved perfect 5/5/5/5 scores across all dimensions. 42 questions scored 1/5 on correctness — nearly all are cross-policy or cross-manual questions where the model either refused or hallucinated.

---

## 2. Performance by Question Type

| Type | Count | Retrieval | Correctness | Faithfulness | Citation |
|---|---|---|---|---|---|
| **calculation** | 12 | 4.67 | **4.33** | 4.33 | 3.92 |
| **procedural** | 25 | **4.84** | 3.88 | 3.96 | **3.72** |
| **factual-lookup** | 29 | 4.48 | 3.93 | 3.83 | 3.38 |
| **edge-case** | 29 | 4.69 | 3.93 | 4.10 | 3.66 |
| **negation** | 15 | 4.33 | 3.93 | 3.87 | 3.33 |
| **colloquial-mapping** | 13 | 4.23 | 3.69 | 3.77 | 2.92 |
| **unanswerable** | 12 | 3.58 | 2.25 | 3.17 | 2.42 |
| **cross-manual** | 20 | 3.95 | 2.75 | 3.10 | 2.40 |
| **cross-policy** | 36 | 3.72 | **1.83** | **2.03** | **1.75** |

**Key findings:**
- **Cross-policy questions are catastrophic** (1.83 correctness). The system cannot reliably compare or synthesize rules across programs.
- **Procedural questions work best for retrieval** (4.84) — the semantic reranker excels when the query describes a workflow that matches a specific policy section.
- **Calculations are the most accurate answer type** (4.33) — when the right chunk is found, numeric answers are reliable.
- **Unanswerable questions** average 2.25 correctness — the model either hallucinates answers or correctly refuses but gets penalized by the judge.

---

## 3. Performance by Failure Mode Tested

| Failure Mode | Count | Retrieval | Correctness | Faithfulness | Citation |
|---|---|---|---|---|---|
| **chunk-boundary** | 21 | **4.90** | **4.24** | **4.29** | **4.10** |
| **specificity-failure** | 22 | 4.68 | 4.23 | 4.09 | 3.59 |
| **table-extraction** | 18 | 4.44 | 3.89 | 3.89 | 3.33 |
| **negation-handling** | 26 | 4.50 | 3.65 | 3.73 | 3.23 |
| **cross-document** | 26 | 4.46 | 3.31 | 3.77 | 3.27 |
| **semantic-mismatch** | 19 | 4.26 | 3.74 | 3.63 | 3.00 |
| **hallucination-bait** | 12 | 3.58 | 2.25 | 3.17 | 2.42 |
| **similar-programs** | 18 | 3.78 | 2.50 | 2.61 | 2.11 |
| **program-interaction** | 8 | 4.12 | 2.38 | 2.62 | 2.25 |
| **conflicting-rules** | 8 | 3.62 | 2.00 | 2.00 | 1.88 |
| **cascading-eligibility** | 7 | 3.43 | 1.57 | 2.00 | 1.57 |
| **multi-document-reasoning** | 6 | 3.67 | 1.67 | 1.83 | 1.67 |

**Findings:**
- **Chunk-boundary is solved** (4.90 retrieval, 4.24 correctness). The chunking strategy handles split content well.
- **Cascading-eligibility and multi-document-reasoning are the hardest failure modes.** These require reasoning chains the current architecture cannot support.
- **Hallucination-bait** exposes when the model fabricates answers (e.g., SNAP allotment tables, Medicaid work requirements) instead of saying "not covered."
- **Similar-programs** fails because the reranker finds chunks from *any* program that discusses the topic, but the model can't differentiate program-specific rules.

---

## 4. Performance by Manual / Question Prefix

| Manual | Count | Retrieval | Correctness | Faithfulness | Citation |
|---|---|---|---|---|---|
| **APM** | 25 | 4.52 | **3.92** | **4.04** | **3.56** |
| **APA** | 28 | 4.36 | 3.79 | 3.93 | 3.21 |
| **MED** (Medicaid) | 30 | **4.50** | 3.67 | 3.83 | 3.37 |
| **TA** (Temp Assistance) | 35 | 4.49 | 3.46 | 3.60 | 3.20 |
| **SNAP** (Food Stamps) | 37 | 4.27 | 3.54 | 3.68 | 3.16 |
| **CROSS** (cross-policy) | 36 | 3.72 | **1.83** | **2.03** | **1.75** |

CROSS questions drag the entire eval significantly. Within single manuals, the system performs well — APM leads with 3.92 correctness.

---

## 5. Performance by Difficulty

| Difficulty | Count | Retrieval | Correctness | Faithfulness | Citation |
|---|---|---|---|---|---|
| easy | 27 | 4.30 | 3.89 | 3.59 | 3.00 |
| medium | 76 | 4.36 | 3.61 | 3.80 | 3.25 |
| hard | 75 | 4.33 | 3.17 | 3.41 | 3.03 |

Surprisingly flat retrieval across difficulty levels — hard questions have similar retrieval (4.33) to easy ones (4.30). The correctness drop from easy→hard is driven by the addition of cross-policy hard questions rather than retrieval failures.

---

## 6. Critical Issue Analysis

### 6.1 False Negatives: Right Retrieval, Wrong Answer (22 questions)

The system retrieved relevant chunks (retrieval ≥ 4) but scored correctness ≤ 1 in **22 cases**. These are the most damaging failures — the system has the information but refuses or misuses it.

| ID | Question | Retrieval | Issue |
|---|---|---|---|
| APM018 | "use good judgment" → Prudent Person Concept | 4 | Refused despite having `prudent_person_judgment.md` in chunks |
| APA010 | Suspension vs. termination of APA cases | 5 | Refused despite having `480-5_suspension_and_termination.md` |
| APA018 | Can someone get both APA and Senior Benefits? | 4 | Refused — couldn't synthesize across manuals |
| TA019 | Can someone on strike get ATAP? | 5 | Refused — had the right chunk |
| TA031 | Village exemption from 60-month limit | 5 | Refused — had the right chunk |
| CROSS* | 16 cross-policy questions | 4–5 | Refused or hallucinated across multi-program questions |

**Root cause:** The system prompt says "If the excerpts don't contain enough information to answer, say 'I don't have enough information.'" The model is being **too conservative** — it sees 10 chunks from multiple files and can't determine if they collectively answer the question.

### 6.2 Hallucination: Fabricated Answers (3 high-severity)

| ID | Question | What happened |
|---|---|---|
| APM023 | SNAP allotment amounts (unanswerable) | Fabricated a full dollar-amount table with Urban/Rural breakdowns |
| TA029 | ATAP cryptocurrency policy (unanswerable) | Invented specific policies about Bitcoin as property |
| APM024 | Medicaid income limits | Provided specific dollar figures that may be from chunks but shouldn't have been presented as APM content |

### 6.3 Incorrect Refusals (38 questions)

45 total refusals: 7 correct (questions were truly unanswerable), **38 incorrect** (questions had answers in the retrieved chunks). This is a **84% false-refusal rate** — a major problem.

---

## 7. Retrieval Analysis

### 7.1 Citation Hit Rate

**71.4%** of expected citation policies were found in the top-10 retrieved chunks (205 out of 287 expected citations). This is a reasonable baseline but leaves ~29% of expected documents unfound.

### 7.2 Chunk Deduplication Problem

- **Average duplicate chunks per question: 3.9** (out of 10 returned)
- **146 questions** (76%) returned 3+ duplicate chunks from the same file
- **71 questions** (37%) returned 5+ duplicate chunks from the same file

This means the effective top-k is often **4–6 unique documents** instead of 10. For cross-policy questions that need chunks from 3+ manuals, this is devastating.

### 7.3 Reranker Scores

The eval results were generated before the `reranker_score` fix, so reranker scores are not available for this run. Future runs will include these for correlation analysis.

---

## 8. Root Cause Attribution: Prompt vs RAG Pipeline

### 8.1 Critical Failures (42 questions scoring 1/5)

| Root Cause | Count | % of Failures | Fix |
|---|---|---|---|
| **Prompt: False refusal** — had the right chunks, said "I don't know" | 22 | 52% | System prompt rewrite |
| **RAG: Retrieval miss** — right docs not in top-10 | 12 | 29% | Dedup, multi-query, synonyms |
| **Prompt: Hallucination** — fabricated answer not in chunks | 4 | 10% | Guardrail prompt |
| **Both: Cross-policy architecture gap** — retrieval partial + model can't synthesize | 4 | 10% | Multi-query retrieval + cross-program prompt |

### 8.2 Partial Failures (45 questions scoring 2–3)

| Root Cause | Count | % | Fix |
|---|---|---|---|
| **RAG: Dedup** — same file ate 4+ slots, missed second source | ~18 | 40% | Dedup chunks by source file |
| **Prompt: Incomplete synthesis** — had chunks, gave partial answer | ~15 | 33% | "Be thorough" prompt tuning |
| **RAG: Synonym/semantic gap** — colloquial term didn't match index terms | ~7 | 16% | Expand synonym map |
| **Prompt: Citation sloppiness** — answer was fine, citations wrong | ~5 | 11% | Citation format instructions |

### 8.3 Overall Split

| Component | % of All Quality Problems | What to Fix |
|---|---|---|
| **Prompt engineering** | **~60%** | Refusal threshold, cross-program instructions, citation format, hallucination guardrails |
| **RAG pipeline** | **~40%** | Chunk dedup, multi-query retrieval, synonym map, semantic config |

### 8.4 Why the 60/40 Split Is Misleading

The problems compound — fixing one side amplifies the other:

- **Dedup is a force multiplier.** Fixing dedup (RAG) gives the model better multi-source context, which reduces false refusals (prompt) — the model often refuses when it sees 6 chunks from the same file and nothing from the second program it needs.
- **Multi-query retrieval fixes both sides at once.** Retrieving chunks from each relevant manual separately solves the retrieval gap AND gives the model structured context that's easier to synthesize.
- **Prompt fix is cheap and fast** (hours). RAG fixes require index changes and re-testing (days).

### 8.5 Recommended Execution Order

| Step | Fix | Effort | Expected Impact |
|---|---|---|---|
| 1 | **Prompt rewrite** — fix refusals, add cross-program instructions, citation format | 1 hour | Rescues ~22 false refusals |
| 2 | **Client-side dedup** — deduplicate chunks by source file before sending to LLM (10 lines in eval.py) | 30 min | +0.3 overall correctness |
| 3 | **Synonym map expansion** — add the 11 missing colloquial→formal mappings | 15 min | +0.1 on semantic-mismatch |
| 4 | **Multi-query retrieval** — detect multi-program questions, issue filtered queries per manual | 2–4 hours | +1.0 on CROSS questions |

Steps 1–2 alone should move overall correctness from **3.31 → ~3.9** and cut the failure rate from 22% to ~8%.

---

## 9. Visual Analysis Summary

12 charts were generated to `eval_charts/`. Key findings from each:

| Chart | File | What It Shows | Key Insight |
|---|---|---|---|
| Score distributions | `01_score_distributions.png` | Histograms for all 4 metrics | Retrieval skews 4–5 (good). Correctness is bimodal — big clusters at 4 and at 1 with a gap at 2 |
| Correctness by question type | `02_correctness_by_question_type.png` | Stacked % bars per type | Cross-policy is ~65% score-1 (wall of red). Calculation/edge-case are almost entirely green |
| Correctness by failure mode | `03_correctness_by_failure_mode.png` | Stacked % bars per mode | cascading-eligibility, multi-document-reasoning, conflicting-rules — nearly 100% failures |
| Type × metric heatmap | `04_heatmap_type_x_metric.png` | 2D heatmap of averages | Clear "quality cliff" — top 6 question types are green (3.7–4.8), bottom 3 drop to orange/red (1.8–2.8) |
| Failure mode × metric heatmap | `05_heatmap_failuremode_x_metric.png` | 2D heatmap of averages | Retrieval stays 3.4–4.9 everywhere, but correctness craters on bottom 5 modes — confirms LLM is the bottleneck, not search |
| Retrieval vs Correctness scatter | `06_retrieval_vs_correctness_scatter.png` | **The RAG gap** | Red dots (cross-policy) cluster in bottom-right quadrant: good retrieval, terrible answers. Blue dots (single-manual) cluster top-right: both good |
| Pass/Fail by manual | `07_pass_fail_by_manual.png` | Stacked pass/partial/fail | CROSS is ~65% fail / ~11% pass. Every single-manual category is 58–72% pass |
| Unique docs vs correctness | `08_unique_docs_vs_correctness.png` | Bar chart | Sweet spot is 2–3 unique docs (avg 4.1 correctness). More unique docs doesn't linearly help because cross-policy questions have many unique docs but still fail (LLM synthesis bottleneck) |
| Refusal analysis | `09_refusal_analysis.png` | Pie + breakdown | 20% of all responses are false refusals; 23 of 38 false refusals are cross-policy type |
| Pipeline quality drop | `10_pipeline_quality_drop.png` | Grouped bars by type | Shows retrieval→correctness→citation degradation per type. The gap widens dramatically for cross-policy and unanswerable |
| Faithfulness vs Correctness | `11_faithfulness_vs_correctness.png` | Quadrant scatter | Bottom-left (both low) = worst failures (hallucinated wrong answers). Bottom-right (faithful but wrong) = refusals |
| Scores by difficulty | `12_scores_by_difficulty.png` | Grouped bars | Retrieval is flat across easy/medium/hard — confirms difficulty impact comes from question type mix, not search quality |

### Key Visual Takeaways

1. **The scatter plot (chart 06) is the most important chart.** It shows the "RAG gap" — retrieval works (x-axis), but answers fail (y-axis) — almost exclusively on cross-policy (red) and cross-manual (orange) questions.

2. **The heatmaps (charts 04–05) confirm the bottleneck is downstream of retrieval.** The leftmost column (retrieval) is consistently green even when the other three columns go red. The problem is what happens after retrieval.

3. **The pass/fail chart (07) makes the CROSS problem visceral.** Every other manual has a healthy green bar. CROSS is a wall of red.

4. **The refusal pie chart (09) quantifies the false-refusal epidemic.** 20% of all responses are refusals, and 84% of those refusals are wrong.

---

## 10. Search Index Configuration Review

### Current Setup
| Component | Configuration |
|---|---|
| **Fields** | `content` (en.microsoft analyzer), `title`, `keywords`, `policy_id`, `manual`, `parent_policy`, `cross_references` |
| **Vector** | `text-embedding-3-large` (1536 dims), HNSW (m=4, efConstruction=400, efSearch=500) |
| **Semantic Config** | title → content → keywords |
| **Scoring Profile** | `policy-boost`: title×3, keywords×2, content×1 |
| **Synonym Map** | 24 entries covering program acronyms |
| **BM25** | Default k1/b (not tuned) |

---

## 11. Recommendations for Azure AI Search Improvements

### 11.1 HIGH PRIORITY: Chunk Deduplication

**Problem:** 76% of queries return 3+ duplicate chunks from the same source file, wasting retrieval slots.

**Fix:** Add a `groupBy` or post-retrieval deduplication on `metadata_storage_name` (or `parent_id`) to ensure top-k returns unique documents first. Alternatively, increase `top_k` to 20 and deduplicate client-side before passing to the LLM, or use the `$filter` approach with multi-stage retrieval.

**Impact:** This alone could push cross-manual retrieval from 3.72 to 4.5+ by retrieving chunks from more diverse sources.

### 11.2 HIGH PRIORITY: Expand the Synonym Map

**Problem:** Colloquial-mapping questions score 3.69 correctness (vs 4.33 for calculations), and semantic-mismatch retrieval averages 4.26. The current synonym map has 24 entries but is missing:

**Missing mappings to add:**
```
good judgment, prudent person, prudent person concept, reasonable judgment
fee agent, volunteer agent, remote agent
sensitive information, confidential case note, domestic violence documentation
collateral contact, third party verification, reference contact
Quest card, EBT, electronic benefits transfer
deliverable fuel, heating oil, fuel oil, propane delivery
in-kind support, free rent, free food, in-kind income
shelter allowance, housing costs, rent portion
ratable reduction, percentage of need
job quit, voluntary separation, voluntary quit
drug felon, drug felony conviction
```

**Impact:** Would directly improve the 19 semantic-mismatch questions (currently 3.74 correctness).

### 11.3 HIGH PRIORITY: Cross-Policy Retrieval Strategy

**Problem:** cross-policy questions average 1.83 correctness. The current architecture retrieves chunks from a single search query, which biases toward one program.

**Options:**
1. **Multi-query retrieval:** For questions mentioning 2+ programs (detect via keyword extraction), issue separate filtered queries per manual and merge results. Use the `manual` field as a filter.
2. **Query expansion:** Before searching, use the LLM to generate program-specific sub-queries. E.g., "How is PFD counted for APA vs SNAP?" → query 1: "PFD income APA" (filter: manual=APA), query 2: "PFD income SNAP" (filter: manual=SNAP).
3. **Increase top_k to 20–30** and deduplicate — brute-force approach that helps but doesn't solve the fundamental issue.

**Impact:** The 36 CROSS questions bring the overall correctness from what would be ~3.9 down to 3.31. Fixing this segment alone would move the overall average by +0.4 points.

### 11.4 MEDIUM PRIORITY: Tune BM25 Parameters

**Problem:** Default BM25 k1/b values may not be optimal for policy documents which tend to be medium-length with repetitive terminology.

**Fix:** Test k1=1.2 (default) vs k1=0.8 (reduces term-frequency saturation) and b=0.75 (default) vs b=0.5 (reduces length normalization penalty for longer chunks). Policy chunks have fairly uniform length, so reducing `b` may help.

### 11.5 MEDIUM PRIORITY: Add manual Field to Semantic Config

**Problem:** The semantic configuration only uses `title`, `content`, and `keywords`. Adding `manual` as a prioritized keyword field would help the reranker understand which program a chunk belongs to, improving cross-manual disambiguation.

**Fix:** Update the semantic configuration:
```json
"prioritizedKeywordsFields": [
  {"fieldName": "keywords"},
  {"fieldName": "manual"}
]
```

### 11.6 MEDIUM PRIORITY: Scoring Profile Enhancement

**Problem:** The current scoring profile only boosts title (3×) and keywords (2×). It doesn't leverage `policy_id` or `manual` fields.

**Fix:** Add freshness boosting or tag-based boosting on the `manual` field if the question can be pre-classified to a specific program. For cross-policy questions, use an equal-weight profile to avoid single-program bias.

### 11.7 LOW PRIORITY: Vector Search Configuration

**Current:** HNSW with m=4, efSearch=500. This is functional but m=4 is low.

**Fix:** Increase `m` to 8–16 for better recall at the cost of index size. The current m=4 means each node has only 4 bi-directional connections, which may miss relevant documents in sparse regions of the vector space.

---

## 12. Recommendations for LLM / Prompt Improvements

### 12.1 HIGH PRIORITY: Fix the Refusal Problem

**Problem:** 38 incorrect refusals out of 45 total (84% false-refusal rate).

**Fix:** Modify the system prompt to be less conservative:
```
Answer the question using ONLY the provided policy excerpts. 
If no excerpts are relevant, say "I don't have enough information."
If excerpts are partially relevant, provide what you can and note any gaps.
DO NOT refuse to answer if you have relevant policy excerpts — provide your best answer 
with appropriate caveats instead.
```

### 12.2 HIGH PRIORITY: Add Cross-Program Instructions

**Fix:** Add to the system prompt:
```
When a question compares or mentions multiple programs (e.g., SNAP vs APA), 
organize your answer by program, addressing each one separately with its specific rules.
Look for program-specific rules even if they appear in different chunks.
```

### 12.3 MEDIUM PRIORITY: Citation Format Instructions

**Problem:** Citation accuracy averages 2.99. The model cites loosely or adds extra sources.

**Fix:** Add explicit citation format instructions:
```
Cite ONLY the specific file name(s) that contain the information you referenced.
Format: [filename.md]. Do not cite files you didn't use for your answer.
```

### 12.4 MEDIUM PRIORITY: Unanswerable Question Handling

**Problem:** The model hallucinated on 3 unanswerable questions (fabricating tables/policies).

**Fix:** Add a guardrail check step. Before returning the answer, have the model self-verify: "Are all specific numbers, dates, and thresholds in my answer traceable to a specific chunk? If any are not, remove them or flag them as uncertain."

---

## 13. Re-Run Recommendations

Before the next eval run:

1. **Capture reranker scores** (already fixed in eval.py) — enables correlation analysis between reranker confidence and answer quality
2. **Add deduplication** — deduplicate chunks by `metadata_storage_name` before passing to the LLM
3. **Expand synonym map** — add the mappings listed in 11.2
4. **Update system prompt** — apply changes from 12.1, 12.2, 12.3
5. **Run only CROSS questions first** — the 36 cross-policy questions are the biggest opportunity; validate improvements before full re-run

---

## Appendix A: Perfect Score Questions (27)

These questions achieved 5/5/5/5 — use them as regression tests:

1. APM002 — Case file retention period (12 months)
2. APM004 — SNAP fair hearing timeline (90 days)
3. APM006 — Returned mail with no forwarding address
4. APM007 — Subpoena handling procedure
5. APM010 — Child abuse reporting steps
6. APM017 — Cannot deny benefits for missing collateral contact
7. APA003 — 2026 APA need standard ($1,356)
8. APA004 — Senior Benefits payment amounts and FPL tiers
9. APA013 — Halfway house APA eligibility (freedom of movement)
10. APA014 — Living in another's household determination
11. APA015 — Assisted living home Senior Benefits eligibility
12. APA026 — Earned income exclusion order for APA
13. SNAP002 — PFD counted as income for SNAP
14. SNAP012 — Self-employment 50% standard deduction for SNAP
15. SNAP015 — GRA cannot pay for phone or utility deposits
16. SNAP029 — PFD garnishment child support deduction
17. SNAP031 — Student under 18 earned income exempt for SNAP
18. SNAP033 — Donated expensive casket disqualifies GRA burial
19. TA003 — Maximum ATAP payment for household of 3 ($923)
20. TA006 — Drug felon qualifying conditions for ATAP
21. TA026 — Childcare exemption from work activities
22. TA027 — Two-parent PASS I childcare work hours
23. MED001 — Transfer of assets look-back period
24. MED009 — Transfer penalty period calculation
25. MED013 — Home transfer exceptions
26. MED014 — Exempt asset transfer types
27. MED028 — Life estate transfer penalty calculation
