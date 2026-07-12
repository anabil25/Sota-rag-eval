# Retrieve Final Architecture Verdict — 2026-07-12

## Decision

**Selected architecture:** `hybrid-reranker`

**Selected configuration:** Azure AI Search hybrid keyword/vector retrieval with the
built-in semantic reranker enabled, `text-embedding-3-large`, `top=10`, vector `k=50`,
`preFilter`, and vector weight `1`.

**Selected run:** `15`

**Selected experiment:** `d472ebc1-3c55-4108-8b01-676c97865167`

## Evaluation Contract

- Environment: `retrieve-v7k2`
- Resource group: `rg-retrieve-v7k2`
- Region: `northcentralus`
- Eval set: `Simple Set` (`eval_set_id=5`)
- Questions: 27 total; 25 active questions with grounded evidence were scored
- Corpus documents: 1,617
- Corpus fingerprint:
  `4fff6583bdc9113be4052735f8076c8d4ccfb8294eb6a6d4278fdaeb6f6f10a2`
- Architecture experiment: `0c7706cb-c1a2-41c2-a193-4c57475166b8`
- Architecture run IDs: `10`, `11`, `13`, `14`

All candidates used the same corpus, eval set, grounded questions, and canonical evidence
ID contract.

## Candidate Results

| Architecture | Recall@5 | Recall@10 | MRR@10 | nDCG@10 | Avg latency | Misses |
|---|---:|---:|---:|---:|---:|---:|
| hybrid-reranker | 0.82 | 0.84 | 0.793 | **0.758** | **906 ms** | **1** |
| agentic-kb | 0.80 | 0.80 | 0.773 | 0.732 | 4,175 ms | 2 |
| lightrag | 0.66 | 0.66 | 0.690 | 0.651 | 5,093 ms | 7 |
| graphrag | 0.40 | 0.62 | 0.362 | 0.384 | 9,455 ms | 7 |

Hybrid-reranker won every primary quality metric and was also the fastest candidate.
GraphRAG was not close enough to justify 300/600-token tuning, a 10% canary, or a full
corpus run.

## Winner Tuning

The only implemented, attribution-safe SOTA control was tested on the same hybrid index.

| Variant | Recall@10 | MRR@10 | nDCG@10 | Avg latency | Misses |
|---|---:|---:|---:|---:|---:|
| semantic reranker on | **0.84** | **0.793** | **0.758** | 925 ms | **1** |
| semantic reranker off | 0.76 | 0.660 | 0.630 | **619 ms** | 3 |

Semantic reranking adds 0.128 nDCG@10 and 0.08 Recall@10 while reducing misses from
three to one, at an average latency cost of about 306 ms. It remains enabled.

## Production Handoff

- Search endpoint: `https://azsrqg6risucd5ba6.search.windows.net`
- Index: `ret-qg6risucd5ba6-hybrid-reranker`
- Semantic configuration: `default-semantic`
- Authentication: Microsoft Entra ID / managed identity; no Search admin keys
- API shape: Azure AI Search data-plane `docs/search`

Example request contract:

```http
POST https://azsrqg6risucd5ba6.search.windows.net/indexes/ret-qg6risucd5ba6-hybrid-reranker/docs/search?api-version=2024-07-01
Authorization: Bearer <managed-identity-token>
Content-Type: application/json

{
  "search": "{userQuestion}",
  "queryType": "semantic",
  "semanticConfiguration": "default-semantic",
  "top": 10,
  "vectorQueries": [
    {
      "kind": "text",
      "text": "{userQuestion}",
      "fields": "content_vector",
      "k": 50,
      "weight": 1
    }
  ]
}
```

The final live smoke used grounded question `3045`; the expected Alaska residency policy
ranked first.

## Loser Cleanup

- Agentic Knowledge Base, knowledge source, base index, indexer, skillset, and data source:
  removed.
- GraphRAG Azure AI Search vector indexes: removed.
- GraphRAG Container Apps Job, managed environment, ACR, UAMI, role assignments,
  delegated subnet, and graph-only NSG: removed.
- Local LightRAG working root: removed.
- GraphRAG Blob run/cache/status artifacts: covered by the deployed Azure-side 30-day
  lifecycle rule; canonical `corpus/` blobs are excluded.
- Loser SQLite architecture statuses: `torn_down`.
- Winner SQLite architecture status: `active`, with run `15`, exact configuration, and
  metrics promoted into its durable config.
- Future IaC reconciliation leaves GraphRAG compute disabled by default. Experiments must
  explicitly set `AZURE_DEPLOY_GRAPH_RUNTIME=true` to recreate it.

## Final Azure Boundary

The retained winner environment contains private/keyless Storage, AI Services, AI Search,
monitoring, the VNet/private endpoint/private DNS path, and the single winner index. The
SvelteKit UI, FastAPI control plane, and SQLite history remain localhost-only by design.

The protected resource group `rg-ret-test2` was not queried, mutated, or deleted.

## Validation

- Backend: 448 passed, 2 skipped
- Frontend: 87 unit tests passed
- Svelte diagnostics: 0 errors, 0 warnings
- Production build: passed
- Ruff, Prettier, ESLint, and `git diff --check`: passed
- Bicep compile: passed
- Production Node audit: 0 vulnerabilities
- Project-scoped Python audit: 0 known vulnerabilities after documented Starlette
  compatibility exceptions
- Device-path scan: no tracked machine-specific paths

## Residual Risk

- GraphRAG Blob evidence expires asynchronously under Azure lifecycle evaluation rather
  than through local data-plane deletion because Storage public access is disabled.
- NLTK and PyArrow advisories remain documented optional GraphRAG dependency exceptions;
  no GraphRAG runtime remains deployed.
- Current Starlette advisories require a release line not yet supported by FastAPI. The
  control API remains loopback-only and mutation-authorized; it must not be exposed as a
  public service without revisiting that dependency boundary.
