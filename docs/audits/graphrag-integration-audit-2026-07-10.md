# GraphRAG 3.1 Integration Audit

**Date:** 2026-07-10  
**Scope:** Retrieve GraphRAG ingestion, configuration, cloud worker, Azure infrastructure, query path, and evaluation integration  
**Upstream version tested:** `graphrag==3.1.0`

## Executive verdict

The integration uses some real GraphRAG interfaces, but several critical pieces are invented, outdated, silently ignored, or incomplete. The 24-hour run was not evidence that GraphRAG normally requires 24 hours for this corpus. It was the combined result of:

1. Three corpus generations being indexed together.
2. Corrupted YAML frontmatter causing recursive filename/title growth.
3. Invalid GraphRAG retry and rate-limit keys that GraphRAG accepted as extras but did not use.
4. A FastGraphRAG graph configuration that retained far more edges than the upstream default.
5. Heavy Azure OpenAI throttling: about 63% of GPT requests returned HTTP 429 during the failed window.
6. Local ephemeral GraphRAG output, logs, and cache, so the hard 24-hour job stop discarded the work needed to resume or diagnose the run.
7. A GraphRAG query/evaluation path that is not functional against GraphRAG 3.1.

Do not restart the full run until the P0 items below are fixed and validated on a small representative corpus.

## Evidence sources

### Official GraphRAG documentation and source

- [GraphRAG 3.1 YAML configuration](https://microsoft.github.io/graphrag/config/yaml/)
- [GraphRAG CLI](https://microsoft.github.io/graphrag/cli/)
- [GraphRAG indexing methods](https://microsoft.github.io/graphrag/index/methods/)
- [GraphRAG input formats and DataFrame API](https://microsoft.github.io/graphrag/index/inputs/)
- [GraphRAG indexing dataflow](https://microsoft.github.io/graphrag/index/default_dataflow/)
- [GraphRAG breaking-change policy](https://github.com/microsoft/graphrag/blob/main/breaking-changes.md)
- [GraphRAG public indexing API](https://github.com/microsoft/graphrag/blob/main/packages/graphrag/graphrag/api/index.py)
- [GraphRAG workflow callbacks](https://github.com/microsoft/graphrag/blob/main/packages/graphrag/graphrag/callbacks/workflow_callbacks.py)

### Microsoft Learn

- [Jobs in Azure Container Apps](https://learn.microsoft.com/azure/container-apps/jobs)
- [Azure OpenAI quota and rate limits](https://learn.microsoft.com/azure/ai-foundry/openai/how-to/quota)
- [Keyless Azure OpenAI connections](https://learn.microsoft.com/azure/developer/ai/keyless-connections)
- [Azure Storage private endpoints](https://learn.microsoft.com/azure/storage/common/storage-private-endpoints)
- [Container Apps private endpoints and DNS](https://learn.microsoft.com/azure/container-apps/private-endpoints-with-dns)

### Additional web evidence

- [GraphRAG discussion: indexing is too slow](https://github.com/microsoft/graphrag/discussions/1971)
- [GraphRAG discussion: skipping community reports](https://github.com/microsoft/graphrag/discussions/1858)
- [GraphRAG issue: cache reuse](https://github.com/microsoft/graphrag/issues/2022)

## What is valid

The following integration choices match GraphRAG 3.1:

- `graphrag init --root ... --model ... --embedding ... --force`
- `graphrag index --root ... --method fast`
- `completion_models` and `embedding_models` blocks
- `model_provider: azure`
- `auth_method: azure_managed_identity`
- `azure_deployment_name`
- `input_storage`, `output_storage`, `reporting`, `cache`, and `vector_store` concepts
- FastGraphRAG as the intended lower-cost indexing method
- Managed identity with `Cognitive Services OpenAI User`
- Private Blob access using the normal Blob hostname resolved to a private endpoint IP

These valid pieces do not compensate for the broken configuration and missing query path below.

## Findings

### P0-1: Retry and rate-limit configuration is invalid and silently ignored

The worker emits model settings like:

```yaml
requests_per_minute: 10
tokens_per_minute: 10000
retry:
  type: exponential_backoff
  max_attempts: 12
  max_retry_wait: 120
```

GraphRAG 3.1 expects:

```yaml
retry:
  type: exponential_backoff
  max_retries: 12
  base_delay: 2
  jitter: true
  max_delay: 120
rate_limit:
  type: sliding_window
  period_in_seconds: 60
  requests_per_period: 10
  tokens_per_period: 10000
```

Installed-package validation proved the effective parsed values were:

- `rate_limit = None`
- `retry.max_retries = None`
- `retry.base_delay = None`
- `retry.max_delay = None`

The invented fields remained attached as allowed extras, which is why basic config loading did not reject them.

**Live consequence:** During the failed 24-hour window, Azure Monitor recorded:

- GPT HTTP 429 requests: `3,338`
- GPT HTTP 200 requests: `1,941`
- Approximate throttled share: `63.2%`

The intended client-side limiter was not active.

**Code:** `retrieve-core/src/retrieve/graphrag_worker/app.py`, `_write_settings()`  
**Bad regression tests:** `retrieve-core/tests/test_provision_index.py`, `TestGraphRAGWorkerSettings`

### P0-2: The GraphRAG query CLI invocation is invalid

The wrapper runs:

```text
python -m graphrag query --root ... --method ... --query "..."
```

GraphRAG 3.1 defines the query as a required positional argument:

```text
graphrag query [OPTIONS] QUERY
```

There is no `--query` option. Executing the current wrapper against the installed package returned an empty result in about two seconds.

**Code:** `retrieve-core/src/retrieve/indexing/advanced.py`, `query_graphrag()`

### P0-3: Query output is fabricated into chunk IDs

Even if the CLI invocation were corrected, the wrapper treats arbitrary answer lines as retrieved chunk IDs:

```python
for line in output.split("\n"):
    chunk_ids.append(line[:100])
```

GraphRAG query output is generated answer text. The public Python query API returns both the response and structured context data. The evaluation path must extract source document/text-unit IDs from that context, not from formatted answer lines.

This means existing GraphRAG retrieval evaluation results cannot be trusted.

### P0-4: The cloud worker cannot query completed indexes

The cloud worker exposes only:

- `GET /health`
- `POST /index`
- `GET /index/{job_id}/status`

It has no `/query` endpoint. The evaluation runner does not pass a graph-worker endpoint or Blob artifact location into `query_graphrag()`. Therefore, even a successful cloud index would not be queryable by the current Step 5/6/7 path.

**Code:**

- `retrieve-core/src/retrieve/graphrag_worker/app.py`
- `retrieve-core/src/retrieve/eval/runner.py`
- `retrieve-core/src/retrieve/indexing/advanced.py`

### P0-5: The corpus contains three accumulated generations

The Blob corpus mirrored the root local corpus of `3,497` Markdown files. Metadata extraction shows the file count is exactly three generations combined:

| Ingest date | Files | Tokens | Estimated 1200-token chunks |
| --- | ---: | ---: | ---: |
| 2026-03-28 | 305 | 295,713 | 422 |
| 2026-04-16 | 1,575 | 1,392,243 | 2,115 |
| 2026-05-09 | 1,617 | 1,664,007 | 2,326 |
| **Total indexed** | **3,497** | **3,351,963** | **4,863** |

The current generation appears to be the 1,617-file May set, subject to domain-owner confirmation.

`run_ingest()` writes current files but never removes files from prior runs. `upload_corpus()` overwrites matching blobs but never deletes stale remote blobs. Therefore both local and cloud corpora accumulate obsolete generations.

### P0-6: YAML frontmatter is corrupted on Windows

`save_doc()` manually writes:

```yaml
source_url: "C:\Users\..."
```

The backslashes are not YAML-escaped. `yaml.safe_load()` fails with `ScannerError`, especially on sequences such as `\U`.

The Markdown plugin then falls back to a title derived from the generated filename. Re-ingesting into the same or another generated corpus produces names such as:

```text
108-5_108_5_108_5_108_5_..._eis_notice_listing.md
```

The audit reproduced this behavior using the current plugin.

Required fixes:

- Serialize frontmatter with `yaml.safe_dump()` instead of manual quoting.
- Reject Markdown ingestion when source and output directories overlap.
- Track source manifests and remove stale outputs from the same source.
- Make Blob upload a true mirror by deleting stale `.md` blobs.

### P0-7: Output, cache, and reporting are ephemeral

The cloud worker configures all three as local files:

```yaml
output_storage:
  type: file
cache:
  storage:
    type: file
reporting:
  type: file
```

It uploads artifacts only after success or a caught Python exception. Azure terminated the replica at its hard `replicaTimeout`, so the worker did not upload the live output, cache, or GraphRAG logs.

GraphRAG 3.1 natively supports Blob-backed output, reporting, and JSON cache through `account_url`, `container_name`, and managed identity. These should be used so each workflow and each LLM cache response persists during execution.

The previous run cannot resume because its cache was destroyed with the replica.

### P1-1: FastGraphRAG graph settings are badly tuned

Official FastGraphRAG guidance says it is generally configured with much smaller chunks, around 50–100 tokens, because relationships are noun-phrase co-occurrence within a chunk.

The worker uses:

```yaml
chunking:
  size: 1200
  overlap: 100
extract_graph_nlp:
  normalize_edge_weights: false
prune_graph:
  min_edge_weight_pct: 0.10
```

Installed GraphRAG 3.1 defaults are:

- `normalize_edge_weights = true`
- `min_edge_weight_pct = 40.0`

`min_edge_weight_pct` is a percentile, not a 0–1 fraction. Setting it to `0.10` retains nearly all edges. Combining almost no edge pruning with 1200-token co-occurrence windows creates an unusually dense, noisy graph and an excessive number of communities/reports.

Do not blindly change the full corpus to 100-token chunks first. Benchmark representative samples at 100, 300, and 600 tokens with default pruning, then select based on graph size, report count, retrieval quality, and cost.

### P1-2: The run was dominated by community report generation

Azure resource metrics for the 24-hour execution window showed:

- GPT requests: `5,279`
- GPT prompt tokens: `13,328,940`
- GPT generated tokens: `7,356,673`
- GPT total inference tokens: `20,685,613`
- Embedding requests: `1`

These are account/deployment metrics and may include other clients using the same deployment, but their timing and sustained pattern match the GraphRAG job. The single embedding request confirms the job never reached the final embedding workflow in a meaningful way.

This is consistent with FastGraphRAG spending its LLM budget in `create_community_reports_text` after constructing an oversized/noisy graph.

### P1-3: Supported progress callbacks are discarded

GraphRAG 3.1 exposes callbacks for:

- pipeline start/end
- workflow start/end
- per-workflow item progress
- pipeline errors

The CLI already registers `ConsoleWorkflowCallbacks`, which prints workflow names and percentages. The worker redirects stdout/stderr to files and reports only `Running GraphRAG index` once per minute.

This is why the UI could not provide a real stage or percent. The worker should use the public `graphrag.api.build_index()` API with a Retrieve-owned callback, or stream and parse the CLI callback output without hiding it.

### P1-4: The GraphRAG dependency is dangerously unpinned

`pyproject.toml` specifies:

```toml
graphrag = ["graphrag>=1.0"]
```

The upstream project explicitly states that `settings.yaml` changes can occur in minor releases and recommends regenerating config with `graphrag init` after upgrades. A wrapper that hardcodes config fields must pin and test an exact compatible minor version.

Recommended initial pin:

```toml
graphrag = ["graphrag==3.1.0"]
```

Upgrade deliberately with schema tests and a generated-config diff.

### P1-5: Cosmos DB is provisioned but unused

Bicep provisions a Cosmos account, database, `entities` container, and `communities` container for GraphRAG. The worker settings use file storage and LanceDB. The cloud request does not pass a Cosmos endpoint, and no code writes GraphRAG artifacts to those containers.

The comments describing Cosmos as the GraphRAG artifact store are false for the implemented path. Remove the resource or explicitly adopt GraphRAG's supported Cosmos storage/table configuration. Do not retain an unused service as architectural decoration.

### P2-1: Two separate GraphRAG config generators can drift

GraphRAG settings are hardcoded independently in:

- the cloud worker
- the local fallback in `advanced.py`

They already differ. There must be one tested settings builder shared by both paths.

### P2-2: Hard-coded duration estimates are unsupported

The UI states `20–90 minutes` without using document count, token count, predicted community count, model quota, or observed throughput. This estimate was not grounded in GraphRAG telemetry.

## Root-cause chain for the 24-hour failure

1. Invalid YAML frontmatter enabled recursive Markdown filename/title growth.
2. Ingestion and Blob upload did not remove stale generations.
3. GraphRAG loaded 3,497 documents instead of the current 1,617-document generation.
4. FastGraphRAG used 1200-token co-occurrence windows, disabled edge normalization, and retained essentially every edge with a 0.1 percentile threshold.
5. The graph generated thousands of communities requiring LLM reports.
6. The client-side rate limiter was absent because its keys were invalid.
7. About 63% of GPT requests were throttled with HTTP 429.
8. Output/cache/reporting were local to the replica.
9. Container Apps enforced the configured 86,400-second hard deadline.
10. The replica was killed before embeddings and before artifact/cache upload.

## Required remediation order

### Phase 1: Make the corpus canonical

1. Preserve the current corpus as an audit backup.
2. Confirm that the 1,617-file 2026-05-09 generation is authoritative.
3. Rewrite frontmatter using valid YAML serialization.
4. Add a source manifest and source/output overlap guard.
5. Mirror the canonical local corpus to Blob, deleting stale Markdown blobs.
6. Validate exact document count, unique source identity, valid YAML, and token count before indexing.

### Phase 2: Make GraphRAG configuration real

1. Pin `graphrag==3.1.0`.
2. Replace retry/rate-limit keys with the GraphRAG 3.1 schema.
3. Restore normalized edge weights and a defensible pruning percentile.
4. Benchmark FastGraphRAG chunk sizes on a representative subset.
5. Generate settings through one shared builder.
6. Run `graphrag index --dry-run` and load the generated file through `GraphRagConfig` in tests.

### Phase 3: Persist work and expose progress

1. Use Blob-backed GraphRAG output, reporting, and cache with managed identity.
2. Use workflow callbacks to persist stage, completed items, total items, and percent.
3. Store per-workflow stats and model metrics in the status object.
4. Make retries reuse the persistent cache.
5. Treat Container Apps timeout as a safety ceiling, not the recovery mechanism.

### Phase 4: Implement a real query/evaluation path

1. Add a cloud query endpoint or a query job/service that loads the completed index.
2. Use the GraphRAG Python query API.
3. Extract document/text-unit evidence from structured `context_data`.
4. Map that evidence to the evaluation corpus IDs.
5. Add smoke tests for local, global, drift, and basic query modes as applicable.
6. Do not mark GraphRAG ready for Steps 5–7 until retrieval IDs and citations are verified.

### Phase 5: Remove unused infrastructure

Remove Cosmos DB unless the implementation is changed to use GraphRAG's supported Cosmos storage path. Update comments and architecture diagrams to match runtime reality.

## Acceptance gates before another full run

- [ ] Canonical corpus count is reviewed and fixed.
- [ ] Every Markdown frontmatter block parses with `yaml.safe_load()`.
- [ ] No source/output directory overlap is allowed for Markdown ingestion.
- [ ] Blob corpus exactly mirrors the canonical local corpus.
- [ ] GraphRAG config round-trips through installed `GraphRagConfig`.
- [ ] `rate_limit` is non-null for both models.
- [ ] Retry fields are `max_retries`, `base_delay`, `jitter`, and `max_delay`.
- [ ] Fast graph settings are benchmarked and documented.
- [ ] Output, reports, and cache are visible in Blob during the run.
- [ ] UI status shows the current workflow and actual progress counts.
- [ ] A 25–50 document representative run completes end-to-end.
- [ ] A query smoke test returns structured source IDs/citations.
- [ ] 429 rate is below the agreed operational threshold.
- [ ] Full-run time/cost estimate is derived from sample throughput and model quota.

## Final assessment

The GraphRAG package itself was invoked, but the integration around it was not production-correct. Several fields and query assumptions appear to have been written without checking the GraphRAG 3.1 contract. The failed run should be treated as invalid experimental evidence, not as a baseline for GraphRAG performance.