# Alaska DPA Policy Search — Run 3 Evaluation Report

**Date:** April 2, 2026  
**Run:** Full 191 questions with all pipeline + eval improvements  
**Changes since Run 1:** Updated system prompt, chunk deduplication (top-20 → 10 unique), semantic answers (extractive), minimumScore 1.5 filter, cross-reference enrichment, structured context by manual, expanded synonym map (24→35), semantic config (manual in keywords), improved judge (full rubric, chunk content visible, no penalty for extra correct info), fixed empty ground truths

---

## 1. Overall Progression

| Metric | Run 1 | Run 2 (merged) | **Run 3** | Δ (v1→v3) |
|---|---|---|---|---|
| **Retrieval** | 4.29 | 4.37 | 4.29 | 0.00 |
| **Correctness** | 3.31 | 3.79 | **3.82** | **+0.51** |
| **Faithfulness** | 3.46 | 3.90 | 3.74 | +0.28 |
| **Citation** | 2.99 | 3.42 | **3.64** | **+0.65** |

### Score Distribution Across Runs

| Score | Run 1 | Run 2 (merged) | **Run 3** |
|---|---|---|---|
| 5 (perfect) | 41 | 44 | **63** |
| 4 (mostly correct) | 63 | 79 | 60 |
| 3 (partial) | 43 | 56 | 46 |
| 2 (mostly wrong) | 2 | 8 | 15 |
| 1 (critical fail) | 42 | 4 | **6** |

### Pass/Fail

| Rate | Run 1 | **Run 3** | Change |
|---|---|---|---|
| **Pass (4-5)** | 104 (54%) | **123 (64%)** | +19 |
| **Partial (2-3)** | 45 (23%) | 61 (31%) | +16 |
| **Fail (1)** | 42 (21%) | **6 (3%)** | **-36** |

**Key takeaway:** Perfect scores (5s) jumped from 41 to 63 (+54%). Failures (1s) dropped from 42 to 6 (-86%). The improved judge rubric is more generous with 5s when answers include all ground truth content plus extra correct details — this is the right behavior.

---

## 2. Performance by Question Type

| Type | Count | Run 1 | **Run 3** | Δ |
|---|---|---|---|---|
| edge-case | 29 | 3.93 | **4.24** | +0.31 |
| factual-lookup | 29 | 3.93 | **4.21** | +0.28 |
| negation | 15 | 3.93 | **4.20** | +0.27 |
| calculation | 12 | 4.33 | 4.00 | -0.33 |
| procedural | 25 | 3.88 | **4.00** | +0.12 |
| colloquial-mapping | 13 | 3.69 | **3.92** | +0.23 |
| cross-manual | 20 | 2.75 | **3.55** | **+0.80** |
| unanswerable | 12 | 2.25 | **3.42** | **+1.17** |
| cross-policy | 36 | 1.83 | **3.06** | **+1.22** |

**Cross-policy improved +1.22 points** — the single biggest category gain. Still below 4.0 but no longer catastrophic.

**Unanswerable improved +1.17** — the anti-hallucination prompt and minimumScore filter are working.

**Calculation dropped -0.33** — some regressions from the judge change (investigation below).

---

## 3. Performance by Failure Mode

| Mode | Count | Run 1 | **Run 3** | Δ |
|---|---|---|---|---|
| table-extraction | 18 | 3.89 | **4.39** | +0.50 |
| negation-handling | 26 | 3.65 | **4.23** | +0.58 |
| cross-document | 26 | 3.31 | **3.96** | **+0.65** |
| specificity-failure | 22 | 4.23 | 3.91 | -0.32 |
| chunk-boundary | 21 | 4.24 | 3.90 | -0.33 |
| semantic-mismatch | 19 | 3.74 | 3.84 | +0.11 |
| similar-programs | 18 | 2.50 | **3.56** | **+1.06** |
| multi-document-reasoning | 6 | 1.67 | **3.50** | **+1.83** |
| hallucination-bait | 12 | 2.25 | **3.42** | **+1.17** |
| program-interaction | 8 | 2.38 | **3.25** | +0.88 |
| conflicting-rules | 8 | 2.00 | **3.12** | +1.12 |
| cascading-eligibility | 7 | 1.57 | **2.71** | +1.14 |

**Multi-document-reasoning had the biggest gain (+1.83)** — the dedup + structured context by manual made multi-source synthesis much more reliable.

**Cascading-eligibility remains the hardest mode** (2.71) — these require reasoning chains across 3+ programs.

**Specificity-failure and chunk-boundary regressed slightly** (-0.32 and -0.33) — likely judge calibration differences rather than pipeline degradation.

---

## 4. Performance by Manual

| Manual | Count | Run 1 | **Run 3** | Δ |
|---|---|---|---|---|
| **APA** | 28 | 3.79 | **4.25** | +0.46 |
| **TA** | 35 | 3.46 | **4.09** | +0.63 |
| **SNAP** | 37 | 3.54 | **3.89** | +0.35 |
| **APM** | 25 | 3.92 | 3.88 | -0.04 |
| **MED** | 30 | 3.67 | **3.87** | +0.20 |
| **CROSS** | 36 | 1.83 | **3.06** | **+1.22** |

APA and TA now both average above 4.0. CROSS still lags but improved dramatically.

---

## 5. Question Movement (Run 1 → Run 3)

| Direction | Count |
|---|---|
| **Improved** | 93 |
| Same | 63 |
| Degraded | 35 |

**49% of questions improved.** 35 degradations need investigation.

### Big Wins (+3 or more points)

| Question | v1→v3 | Type |
|---|---|---|
| APM018 (prudent person concept) | 1→**5** | colloquial-mapping |
| TA019 (on strike + ATAP) | 1→**5** | negation |
| TA029 (cryptocurrency policy) | 1→**5** | unanswerable |
| APA010 (suspension vs termination) | 1→**4** | procedural |
| SNAP007 (child support TANF/non-TANF) | 1→**4** | edge-case |
| SNAP030 (HAP vs SNAP income calc) | 1→**4** | cross-manual |
| SNAP034 (HAP vs SNAP expedited) | 1→**4** | cross-manual |
| TA004 (quit job + ATAP) | 1→**4** | edge-case |
| TA031 (village exemption 60-month) | 1→**4** | edge-case |
| CROSS008, CROSS017, CROSS019, CROSS020, CROSS030 | 1→**4** | cross-policy |

### Notable Regressions

| Question | v1→v3 | Type | Likely Cause |
|---|---|---|---|
| APM015 (cousin's case) | 5→**1** | negation | False refusal — needs investigation |
| APM007 (subpoena handling) | 5→**3** | procedural | Judge may be stricter on completeness |
| APA026 (earned income exclusions) | 5→**3** | calculation | Judge now sees chunk content, may notice minor gaps |
| APM022 (closure notice timing) | 5→**3** | calculation | Same — judge recalibration |
| APM011 (Ombudsman records) | 5→**3** | edge-case | Possible retrieval shift from minimumScore filter |

---

## 6. Remaining Failures

### Score 1 (6 questions)

| ID | Type | Mode | Issue |
|---|---|---|---|
| APM015 | negation | negation-handling | "Can I work on my cousin's case?" — false refusal |
| SNAP017 | factual-lookup | specificity-failure | GRA burial max payment — false refusal |
| SNAP022 | colloquial-mapping | semantic-mismatch | "collateral contact" definition — false refusal |
| SNAP036 | unanswerable | hallucination-bait | Child care subsidy + SNAP — should refuse but may be mishandling |
| TA005 | edge-case | negation-handling | Drug felon kids' benefits — not answering correctly |
| MED027 | cross-manual | specificity-failure | Pregnant woman Medicaid duration — false refusal |

**4 of 6 remaining score-1s are false refusals** — the prompt reduced refusals from 38 to 12, but didn't eliminate them entirely for edge cases where the model is uncertain.

### Score 2 (16 questions)

| Pattern | Count | Examples |
|---|---|---|
| Cross-policy rule confusion | 6 | CROSS001, CROSS011, CROSS021, CROSS022, CROSS026, CROSS033 |
| Cross-manual retrieval gap | 3 | APA017, APA019, SNAP008 |
| Wrong number extracted | 2 | APM005, MED003 |
| Unanswerable handling | 2 | SNAP035, TA034 |
| Other | 3 | SNAP032, MED005, MED027 |

### Refusal Analysis

| Metric | Run 1 | Run 2 | **Run 3** |
|---|---|---|---|
| Total refusals | 45 | 4 | **12** |
| False refusals | 38 | 4 | **12** |
| Correct refusals | 7 | 0 | **0** |

False refusals increased from 4 (Run 2) to 12 (Run 3). This is because Run 3 evaluated all 191 questions fresh (not just re-run failures), so some questions that passed at score 4 in Run 1 now got refused due to the minimumScore filter dropping chunks below 1.5.

### Dedup & Reranker

| Metric | Run 1 | Run 3 |
|---|---|---|
| Avg unique docs/query | 6.0 | **8.9** |
| Avg reranker score | N/A | 2.341 |

---

## 7. What Worked

| Change | Evidence |
|---|---|
| **New judge rubric (every score 1-5 defined)** | Score-5 count: 41→63. Score-1 count: 42→6. Distribution is now a proper bell curve, not bimodal. |
| **Judge sees chunk content** | Faithfulness scores now reflect what's actually in the chunks, not guesses from file names. |
| **Don't penalize extra correct info** | Questions that were scored 3-4 for "too much detail" now correctly score 5 when all ground truth points are covered. |
| **System prompt rewrite** | Refusals 45→12. Cross-policy correctness 1.83→3.06. |
| **Chunk deduplication** | 6.0→8.9 unique docs/query. Cross-document mode: 3.31→3.96. |
| **Semantic answers (extractive)** | Gives model pre-extracted key passages to cross-reference against. |
| **Synonym map expansion** | APM018 (prudent person): 1→5. Colloquial-mapping: 3.69→3.92. |

## 8. What Didn't Work or Regressed

| Issue | Detail |
|---|---|
| **35 regressions** | 18% of questions scored lower in Run 3 than Run 1. Most are -1 point drops (5→4 or 4→3) from judge recalibration, but APM015 dropped 5→1. |
| **minimumScore filter too aggressive?** | The 1.5 threshold may be dropping marginally relevant chunks that the model previously used. 12 false refusals suggests some questions lose too many chunks. |
| **Chunk-boundary and specificity-failure modes regressed** | These were already strong in Run 1 (4.24 and 4.23) and dropped to 3.90 and 3.91. Structured context by manual may have slightly changed the presentation order. |
| **Calculation type dropped** | 4.33→4.00. The no-max-tokens change may produce longer answers that the judge picks apart more. |
| **False refusals still at 12** | Down from 38 but not zero. 8 of 12 are cross-policy questions. |

---

## 9. Run 3 Scorecard

| Metric | Run 1 | Run 2 | **Run 3** | Target |
|---|---|---|---|---|
| Overall correctness | 3.31 | 3.79 | **3.82** | 4.0+ |
| Pass rate (4-5) | 54% | 64% | **64%** | 80%+ |
| Score-1 count | 42 | 4 | **6** | 0 |
| Score 1+2 count | 44 | 12 | **22** | 0 |
| Score-5 count | 41 | 44 | **63** | 80+ |
| False refusals | 38 | 4 | **12** | 0 |
| CROSS correctness | 1.83 | ~2.8 | **3.06** | 4.0+ |

---

## 10. Recommendations for Run 4

### Investigate & Fix the Regressions

1. **APM015 (5→1)**: This was a perfect score that became a failure. Check if the minimumScore filter dropped the key chunk. If so, lower the threshold to 1.0 or remove it.

2. **The 35 degradations**: Most are -1 point. Separate judge-calibration effects from actual pipeline degradation by re-running the same Run 1 answers through the Run 3 judge to see how many score changes are purely from the new rubric.

### Address Remaining False Refusals (12)

3. **Lower minimumScore from 1.5 to 1.0** — or remove it entirely and let the model decide. The filter is too aggressive for some legitimate queries.

4. **Add a "never refuse on these topics" list** — for well-known concepts like "collateral contact" (SNAP022) or "cousin's case" (APM015) where the model has chunks but refuses.

### Close the Cross-Policy Gap (CROSS at 3.06)

5. **Multi-query retrieval** for CROSS questions remains the highest-value change. The current single-query approach improved from 1.83→3.06 but can't reliably get chunks from all needed programs.

6. **Alternatively, increase DEDUP_TARGET from 10 to 15** for questions that mention 2+ programs — more context from more programs.

### Fix Wrong-Number Extraction (APM005, MED003)

7. **Table-aware chunking** — these failures persist across all 3 runs because the source chunk contains multiple years' data and the model picks the wrong row.
