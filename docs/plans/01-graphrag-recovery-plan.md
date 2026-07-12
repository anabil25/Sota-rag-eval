# Plan 1 — Repair GraphRAG End to End

**Status:** Complete — GraphRAG evaluated as a candidate; hybrid-reranker selected
**Priority:** P0
**Last updated:** 2026-07-12

## Goal

Replace the failed experimental GraphRAG path with a pinned, schema-validated GraphRAG 3.1 integration over one canonical corpus, persistent cloud artifacts/cache, real workflow progress, and a functional query/evaluation adapter. Do not modify upstream GraphRAG source.

## Safety gates

- Block new full-corpus GraphRAG starts until representative and canary runs pass.
- Preserve the failed execution, metrics, Blob listings, corpora, and SQLite state as audit evidence.
- Do not overwrite `indexes/current` during a run. Promote an immutable successful run only after validation.
- Do not start another paid full run without explicit gate approval.

## Implementation progress — batch 1

- [x] Full-corpus GraphRAG starts are default-denied unless
	`RETRIEVE_GRAPHRAG_FULL_RUN_APPROVED=true` is explicitly set.
- [x] Sample and canary scopes require enforced document caps (50 and 500 maximum,
	respectively), including a cap in the worker Blob download loop.
- [x] Jobs reject `indexes/current` as an output prefix and default to immutable
	`indexes/<job-id>` artifacts.
- [x] Frontmatter is serialized with `yaml.safe_dump()` and round-trip validated;
	malformed source frontmatter is rejected instead of recursively regenerated.
- [x] Resolved same/parent/child source-output overlap is rejected, including symlink
	aliases where the platform permits symlink creation.
- [x] `graphrag==3.1.0` is pinned; worker and local paths use one settings builder.
- [x] Generated settings use recognized retry/rate-limit fields, normalized edge
	weights, and 40th-percentile edge pruning, then parse through `GraphRagConfig`.
- [x] A recursive Pydantic-extra check rejects settings GraphRAG would silently ignore.
- [x] Corpus manifest/mirror, persistent native storage, callbacks, public API
	execution, reconciliation, and structured query/evidence integration are implemented.
	The representative chunk benchmark remains a live rollout gate.

## Current completion checkpoint — 2026-07-11

- [x] Canonical manifest, stable source/content/GraphRAG IDs, tamper detection, and exact file-set validation.
- [x] Manifest-owned Blob mirror with unmanaged-file blocking, manifest-last commit, and exact dry-run-plan admission before deletion.
- [x] GraphRAG 3.1 Blob output/cache/reporting, Azure AI Search vectors, public `build_index()`, workflow callbacks, heartbeat, and immutable run prefixes.
- [x] Manual Container Apps Job launch with per-execution corpus, scope, cap, chunk-size, and overlap controls.
- [x] Reconciliation requires Azure execution and durable Blob status agreement; hard timeout/failure overrides stale progress.
- [x] Localhost queries load only successful immutable Blob runs and return canonical document IDs/citations.
- [x] Evaluation consumes the persisted endpoint/artifact/fingerprint/storage contract.
- [x] Full-corpus execution remains default-denied; sample and canary caps are enforced.
- [x] Live pipeline smoke exposed zero golden-set coverage in lexicographic first-N sampling; bounded runs now use deterministic corpus-wide selection and can require all golden evidence documents, with selected IDs persisted for reconciliation.
- [x] Live representative 50-document, 100-token run completed with all 17 grounded
	evidence documents included and structured query evidence validated.
- [x] Same 25-question eval completed across hybrid-reranker, Agentic KB, GraphRAG,
	and LightRAG.
- [x] Stop gate applied: GraphRAG nDCG@10 was 0.384 versus hybrid-reranker 0.758,
	so 300/600-token tuning, canary, and full-corpus execution were not justified.
- [x] GraphRAG loser indexes/runtime removed; Blob evidence has 30-day Azure lifecycle
	retention.

### Live pipeline smoke evidence

- Execution `azgrjqg6risucd5ba6-sh506ft` completed all 10 GraphRAG workflows with zero workflow or model-response failures.
- Immutable artifact: `runs/4fff6583bdc9113be4052735f8076c8d4ccfb8294eb6a6d4278fdaeb6f6f10a2/af2d420a58ec48f1bd930d8f30063ae4`.
- Shape: 50 documents, 100-token chunks, 20-token overlap, 980 entity vectors, 249 community vectors, and 764 text-unit vectors.
- Duration and usage: 5,568 seconds; 253 GPT-4.1 requests / 1,451,330 tokens; 99 embedding requests / 216,719 tokens.
- Classification: pipeline smoke only. Lexicographic first-50 selection covered 0 of the 25 answerable `Simple Set` questions and is not accepted as a quality benchmark.

## Phase 1 — Canonical corpus

1. Fix `save_doc()` in `retrieve-core/src/retrieve/ingest/run.py` to serialize frontmatter with `yaml.safe_dump()` and validate round trips.
2. Add stable logical source IDs and content hashes to an ingestion manifest.
3. Reject source/output overlap, including resolved parent/child and symlink overlap.
4. Re-ingest into a new empty staging directory from the authoritative source.
5. Compare staged content to the March, April, and May historical generations; require review of adds/removes/changes.
6. Extend `upload_corpus()` into a dry-run, manifest-driven mirror that deletes only stale managed Markdown blobs after count/hash verification.
7. Define one canonical document/evidence ID contract shared by eval generation, Search, GraphRAG, LightRAG, and scoring.
8. Gate completion on valid YAML, unique sources, approved count, no recursive filenames, stable corpus fingerprint, and local/Blob parity.

## Phase 2 — Correct GraphRAG 3.1 configuration

1. Pin `graphrag==3.1.0` and lock container dependencies.
2. Create one shared settings builder under `retrieve-core/src/retrieve/graphrag/`.
3. Replace invented retry fields with `max_retries`, `base_delay`, `jitter`, and `max_delay`.
4. Replace top-level RPM/TPM fields with nested `rate_limit.period_in_seconds`, `requests_per_period`, and `tokens_per_period`.
5. Parse every generated config with installed `GraphRagConfig`; reject unexpected Retrieve-owned extras.
6. Restore normalized edge weights and defensible percentile pruning.
7. Benchmark FastGraphRAG chunk sizes 100, 300, and 600 on 25–50 representative documents. Select by graph density, report count, cost, duration, and retrieval quality.
8. Run GraphRAG `index --dry-run` before any model calls.

## Phase 3 — Persistent execution and real progress

1. Use GraphRAG native Blob storage for output tables, reporting, update output, and JSON cache through managed identity.
2. Use immutable prefixes: `runs/<corpus-fingerprint>/<run-id>/`.
3. Prefer Azure AI Search as the persistent vector store; validate schemas, dimensions, audience, and RBAC.
4. Replace the hidden CLI subprocess with public `graphrag.api.build_index()`.
5. Implement a Retrieve `WorkflowCallbacks` adapter for workflow/item progress, errors, and pipeline completion.
6. Persist status, callback progress, stats, context, logs, cache, model metrics, timestamps, and heartbeat throughout execution.
7. Add a durable state machine: queued, preparing, running, succeeded, failed, cancelled, timed_out.
8. Reconcile Container Apps Job and Blob state into SQLite automatically on startup and refresh.
9. Promote `indexes/current` atomically only after output, vector, and query validation.

## Phase 4 — Real query/evidence integration

1. Remove the invalid GraphRAG `--query` CLI invocation and answer-line-to-ID parsing.
2. Implement a query adapter using public GraphRAG query APIs and structured context.
3. Add an authenticated internal query endpoint accepting index alias/fingerprint, mode, query, and limits.
4. Return answer, text-unit IDs, document IDs, citations, latency, and model metrics.
5. Map GraphRAG context IDs to canonical corpus/eval IDs without fabricated values.
6. Update `retrieve-core/src/retrieve/eval/runner.py` to score structured evidence.
7. Enable evaluation only for a promoted successful index.
8. Update SvelteKit to display actual workflow/item progress and reconciled status.

## Phase 5 — Tests and rollout

1. Unit tests: Windows YAML paths, overlap guard, manifests, Blob mirror boundaries, fingerprint stability, config parsing, retry/rate fields, pruning, callback math, alias promotion, query evidence, and state transitions.
2. Contract tests against exactly GraphRAG 3.1.0 for config, workflows, callback signatures, query result shape, and Blob providers.
3. Deterministic local integration using mocked LLM/embedding providers.
4. Azure representative sample: persistent artifacts visible during execution, restart recovery, verified query citations, 429 rate below 5%.
5. Ten-percent canary: compare observed time/cost/graph quality with prediction; abort outside tolerance.
6. Full run only after canary approval; timeout comes from measured throughput plus safety margin.

## Key files

- `docs/audits/graphrag-integration-audit-2026-07-10.md`
- `retrieve-core/src/retrieve/ingest/run.py`
- `retrieve-core/src/retrieve/ingest/markdown_plugin.py`
- `retrieve-core/src/retrieve/indexing/blob_upload.py`
- `retrieve-core/src/retrieve/graphrag_worker/app.py`
- `retrieve-core/src/retrieve/graphrag_worker/run_job.py`
- `retrieve-core/src/retrieve/indexing/advanced.py`
- `retrieve-core/src/retrieve/eval/runner.py`
- `retrieve-core/src/retrieve/indexing/run.py`
- `retrieve-core/pyproject.toml`
- `src/routes/flow/[step]/+page.svelte`
- `src/lib/components/JobProgressStream.svelte`

## Acceptance criteria

- One reviewed canonical corpus and exact Blob mirror.
- Generated settings parse with active rate limiter and recognized retries.
- Persistent output/cache/reporting survive worker death.
- UI shows real workflow/item progress.
- Query returns verified structured source evidence.
- Representative and canary runs meet correctness, cost, duration, and throttle targets.
- No full paid run before all gates pass.
