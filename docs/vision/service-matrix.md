# Retrieve — Service Matrix

> Which parts of Retrieve spin up which Azure services, and in what order.
>
> Design context: [Retrieve.md](Retrieve.md) | Skills reference: [../reference/skills/](../reference/skills/)

---

## Deployment Order (Universal)

Every architecture follows this dependency chain. Steps marked with ◆ are architecture-specific and may be skipped.

```
1. Storage Account + Blob Container          ← ALL architectures
     ↓
2. AI Foundry / OpenAI Account               ← All except keyword-only
     ↓  model deployments
     ↓
3. Azure AI Search Service                   ← ALL architectures
     ↓  managed identity created
     ↓
4. Role Assignments (Search→Blob, Search→OpenAI)
     ↓
◆5. Cosmos DB (Serverless)                   ← GraphRAG only
     ↓
◆6. Azure Functions (Flex Consumption)       ← GraphRAG only
     ↓  managed identity created
     ↓
◆6b. Azure Container Apps                     ← LightRAG only (built-in server)
     ↓
◆7. Role Assignments (Func→Search, Func→Cosmos, Func→OpenAI)
     ↓
8. Create Index + Data Source + Skillset + Indexer   (via REST/SDK, not Bicep)
   ⚠️  SKIPPED for Agentic (KB) — Knowledge Source auto-ingest handles this
```

---

## Native Capabilities — What AI Search Handles Without External Services

> **2025-11-01-preview**. Before spinning up any external service, check if AI Search handles it natively.

| Capability | Native Feature | Eliminates |
|---|---|---|
| Multi-hop agentic retrieval | Knowledge Bases API (`reasoningEffort: "medium"`) | Azure Functions orchestrator |
| Query rewriting / expansion | `queryRewrites: "generative"` (semantic query type) | External LLM query expansion |
| Answer extraction | `answers: "extractive"` query param | External answer extraction |
| Document captions | `captions: "extractive"` query param | External summarization |
| Semantic reranking (cross-encoder) | `queryType: "semantic"` with `SemanticConfiguration` | External cross-encoder model |
| Auto-ingest from blob | Knowledge Source kind `azureBlob` | Custom data source + indexer + skillset |
| Auto-ingest from SharePoint | Knowledge Source kind `indexedSharePoint` / `remoteSharePoint` | SharePoint connector code |
| Auto-ingest from OneLake | Knowledge Source kind `indexedOneLake` | Fabric connector code |
| Live web search | Knowledge Source kind `web` | Bing API integration |
| LLM enrichment at index time | `ChatCompletionSkill` in skillset | Azure Functions + LLM |
| Document chunking | `SplitSkill` (chars or tokens) | Custom chunking code |
| Markdown section splitting | `parsingMode: "markdown"`, `markdownParsingSubmode: "oneToMany"` | Custom parsing code |
| Document cracking (PDF/images) | `DocumentIntelligenceLayoutSkill` | External Document Intelligence calls |
| Vector embedding at index time | `AzureOpenAIEmbeddingSkill` | External embedding pipeline |
| Vector embedding at query time | `AzureOpenAIVectorizer` / `AMLVectorizer` | Client-side embedding |
| Spell correction | `speller: "lexicon"` | External spell check |
| Vector compression | Scalar / binary quantization with rescoring | External quantization |
| Security trimming | Permission ingestion + `x-ms-query-source-authorization` | Custom ACL logic |
| Answer synthesis (RAG) | Knowledge Base `outputMode: "answerSynthesis"` | External RAG code |

### Cosmos DB for NoSQL Native Capabilities (new)

Cosmos DB for NoSQL now also has built-in capabilities that overlap with AI Search:

| Capability | Cosmos DB Status | Competing AI Search Feature |
|---|---|---|
| DiskANN vector search | GA (up to 4,096 dim) | HNSW vector search |
| Full-text / BM25 search | GA | Keyword search |
| Hybrid search (vector + text + filters) | GA | Hybrid search + RRF |
| Document store with embeddings | GA | Blob + indexer + vector fields |
| Graph traversal | **NO** | Knowledge Bases agentic reasoning |
| Built-in LLM enrichment (index-time) | **NO** | ChatCompletionSkill |
| Semantic reranking | **NO** | Built-in semantic reranker |
| Auto-ingest from blob/SharePoint | **NO** | Knowledge Sources |

**Implication:** Cosmos DB could serve as a **unified store** (replacing Blob + AI Search) for simpler architectures, but AI Search still offers more retrieval intelligence (reranking, agentic reasoning, skillsets, Knowledge Bases). For the Retrieve accelerator, Cosmos DB is primarily used as the **GraphRAG artifact store** and as a potential **alternative backend** for LightRAG (via MongoDB vCore).

> **RETIRED: Cosmos DB for PostgreSQL** — if LightRAG needs PostgreSQL (pgvector + Apache AGE for graph), use **Azure Database for PostgreSQL Flexible Server** — a separate Azure service. See `docs/reference/skills/azure-cosmos-db.md`.

---

## Architecture × Azure Service Matrix

### Resources Provisioned

| Architecture | Storage Account | Blob Container | AI Foundry Account | Embedding Deployment | LLM Deployment | AI Search | Cosmos DB | Azure Functions | Container Apps |
|---|---|---|---|---|---|---|---|---|---|
| **Keyword only** | ✓ | ✓ | — | — | — | ✓ Basic | — | — | — |
| **Single vector** | ✓ | ✓ | ✓ | ✓ | — | ✓ Basic | — | — | — |
| **Hybrid** | ✓ | ✓ | ✓ | ✓ | — | ✓ Basic | — | — | — |
| **Hybrid + reranker** | ✓ | ✓ | ✓ | ✓ | — | ✓ Basic (semantic) | — | — | — |
| **Hybrid + LLM enrichment** | ✓ | ✓ | ✓ | ✓ | ✓ (ChatCompletionSkill) | ✓ Basic | — | — | — |
| **Multi-vector (BGE-M3)** | ✓ | ✓ | ✓ | ✓ (managed compute) | — | ✓ Basic | — | — | — |
| **Agentic (Knowledge Base)** | ✓ | ✓ | ✓ | ✓ | ✓ | ✓ Basic | — | — | — |
| **GraphRAG** | ✓ | ✓ | ✓ | ✓ | ✓ | ✓ Basic | ✓ Serverless | ✓ | — |
| **LightRAG** | ✓ | ✓ | ✓ | ✓ | ✓ | ✓ Basic | — | — | ✓ Container Apps |

> **Removed: "Agentic retrieval" (Function-based).** The Knowledge Bases API handles multi-hop agentic retrieval natively. Retrieve queries persisted GraphRAG artifacts from localhost; no Function endpoint is required. See `docs/reference/skills/azure-functions.md`.
>
> **Added: "Hybrid + LLM enrichment".** Uses ChatCompletionSkill at index time to extract cross-references, generate summaries, and classify topics. Adds an LLM deployment but no Functions. This is a mid-tier option between pure hybrid and full agentic/GraphRAG.
>
> **LightRAG is local-first in the current topology.** Retrieve runs the pinned LightRAG SDK locally against Azure AI models and persists experiment state locally. A hosted LightRAG service is a future, separately approved topology. See `docs/reference/skills/graphrag-lightrag.md`.

### AI Foundry Model Deployments Per Architecture

| Architecture | Embedding Model | LLM Model | Purpose |
|---|---|---|---|
| Keyword only | — | — | No models needed |
| Single vector | text-embedding-3-large | — | Document + query embedding |
| Hybrid | text-embedding-3-large | — | Document + query embedding |
| Hybrid + reranker | text-embedding-3-large | — | Embedding (semantic reranker is built into AI Search) |
| Hybrid + LLM enrichment | text-embedding-3-large | GPT-4.1 | Embedding + ChatCompletionSkill at index time |
| Multi-vector (BGE-M3) | ✓ (Foundry managed compute) | — | BGE-M3 deployed via Foundry managed compute endpoint |
| Agentic (Knowledge Base) | text-embedding-3-large | GPT-4.1 | Embedding + KB query planning LLM |
| GraphRAG | text-embedding-3-large | GPT-4.1 | Embedding entities + extraction/summarization |
| LightRAG | text-embedding-3-large | GPT-4.1 | Embedding + extraction |

### AI Search Index Configuration Per Architecture

| Architecture | Vector Fields | Keyword Fields | Semantic Config | Vectorizer | Skillset |
|---|---|---|---|---|---|
| Keyword only | — | ✓ content, title, policy_id | — | — | — |
| Single vector | ✓ content_vector | ✓ content, title, policy_id | — | AzureOpenAI | AzureOpenAIEmbeddingSkill |
| Hybrid | ✓ content_vector | ✓ content, title, policy_id | — | AzureOpenAI | AzureOpenAIEmbeddingSkill |
| Hybrid + reranker | ✓ content_vector | ✓ content, title, policy_id | ✓ semantic config | AzureOpenAI | AzureOpenAIEmbeddingSkill |
| Hybrid + LLM enrichment | ✓ content_vector | ✓ content, title, policy_id, referenced_policies, topics, summary | ✓ semantic config | AzureOpenAI | AzureOpenAIEmbeddingSkill + ChatCompletionSkill |
| Multi-vector (BGE-M3) | ✓ dense_vector, sparse_vector | ✓ content, title, policy_id | — | AMLVectorizer (Foundry) | AMLSkill (Foundry managed compute) |
| Agentic (Knowledge Base) | Managed by KB | Managed by KB | Managed by KB | Managed by KB | Managed by KB |
| GraphRAG | ✓ entity_vector | ✓ entity_name, description | — | AzureOpenAI | Custom (graphrag index) |
| LightRAG | ✓ content_vector | ✓ content | — | AzureOpenAI | Custom (lightrag insert) |

---

## Role Assignment Matrix

| Role | Role ID | Keyword | Single Vec | Hybrid | Hybrid+RR | Hybrid+LLM | BGE-M3 | Agentic (KB) | GraphRAG | LightRAG |
|---|---|---|---|---|---|---|---|---|---|---|
| **Blob Data Reader → Search** | `2a2b99...` | ✓ | ✓ | ✓ | ✓ | ✓ | ✓ | ✓ | ✓ | ✓ |
| **Blob Data Contributor → Deployer** | `ba92f5...` | ✓ | ✓ | ✓ | ✓ | ✓ | ✓ | ✓ | ✓ | ✓ |
| **OpenAI User → Search** | `5e0bd9...` | — | ✓ | ✓ | ✓ | ✓ | — | ✓ | ✓ | ✓ |
| **Index Data Reader → Functions** | `1407120...` | — | — | — | — | — | — | — | ✓ | — |
| **OpenAI User → Functions** | `5e0bd9...` | — | — | — | — | — | — | — | ✓ | — |
| **Cosmos Data Contributor → Functions** | Built-in | — | — | — | — | — | — | — | ✓ | — |

---

## Retrieve Phase → Azure Operations

| Retrieve Phase | Azure Operations | Services Touched |
|---|---|---|
| **1. Ingest** | None (local only) | — |
| **2. Golden Eval Set** | None (uses Copilot SDK, local) | — |
| **3a. Test Mode Selection** | None (UI only) | — |
| **3b. SOTA Mode Selection** | None (UI only) | — |
| **4. Provision** | Deploy Bicep templates per architecture | Storage, AI Foundry, AI Search, Cosmos DB, Functions |
| **4. Index** | Upload blobs, create data source, create index, create skillset, run indexer | Storage (blob upload), AI Search (index/indexer/skillset), AI Foundry (embedding calls) |
| **5. Evaluate** | Query each architecture's search endpoint, collect results | AI Search (queries), AI Search KB (agentic-kb queries), Functions (GraphRAG queries), Container Apps (LightRAG queries), AI Foundry (Copilot SDK for failure classification) |
| **6. Teardown** | Delete unselected resources | Delete: indexes, Cosmos DB accounts, Function Apps, Container Apps, model deployments |

---

## SOTA Eval Mode — Components × Azure Resources

When toggling components within a SOTA path, each toggle variation creates a different **index configuration** on the same AI Search service. The base Azure resources stay the same.

| Toggle | What Changes | Azure Impact |
|---|---|---|
| Semantic reranker on/off | `semanticConfiguration` in index + `queryType: "semantic"` | Same Search service, different index config. **This IS a cross-encoder** — no need for a separate cross-encoder deployment. |
| LLM enrichment on/off | Add `ChatCompletionSkill` to skillset | Needs LLM deployment in Foundry. Rebuilds index. No Functions. |
| Embedding model swap | Different deployment (3-small vs 3-large) | Different model deployment, rebuild index |
| Chunk size change (256/512/1024) | Skillset `SplitSkill` config | Same resources, different skillset, rebuild index |
| Markdown section splitting | `markdownParsingSubmode: "oneToMany"` + `markdownHeaderDepth` | No skillset needed at all. Zero-cost chunking. Indexer config change only. |
| Late chunking vs fixed | `DocumentIntelligenceLayoutSkill` with `chunkingProperties` vs `SplitSkill` | Same resources. DocIntelligence is structure-aware (preserves headings, tables). |
| Query rewrites on/off | `queryRewrites: "generative"` query parameter | No resource change. **Built-in** — no LLM deployment needed. |
| Extractive answers on/off | `answers: "extractive"` query parameter | No resource change. Built-in. |
| RRF fusion weights | Query-time parameter | No resource change |
| Reasoning effort (KB only) | `reasoningEffort: minimal/low/medium` | No resource change. Controls KB query planning depth. |

**Key insight:** Most SOTA toggles only change the Search index/skillset/query configuration, not the Azure resources. This is why SOTA mode is cheaper than Test mode — you're not spinning up entirely new services, just rebuilding indexes.

---

## Estimated Costs Per Architecture (Eval Run)

| Architecture | Per-Hour Eval Cost | Dominant Cost | Monthly Production |
|---|---|---|---|
| Keyword only | ~$0.10 | AI Search Basic | ~$70 |
| Single vector | ~$0.30 | AI Search + embedding TPM | ~$180 |
| Hybrid | ~$0.30 | AI Search + embedding TPM | ~$190 |
| Hybrid + reranker | ~$0.40 | AI Search + embedding TPM + semantic | ~$280 |
| Hybrid + LLM enrichment | ~$0.50 | AI Search + embedding + LLM (index-time) | ~$300 |
| Multi-vector (BGE-M3) | ~$0.80 | Foundry managed compute + AI Search | ~$320 |
| Agentic (KB) | ~$0.60 | AI Search KB + LLM (query planning) | ~$350 |
| GraphRAG | ~$3.00 | Indexing ($10-30) + Cosmos DB + Functions | ~$850 |
| LightRAG | ~$0.80 | Container Apps + LLM calls | ~$350 |

Costs are rough estimates for a 300-document corpus and ~150 eval queries. Actual costs vary by region, TPM allocation, and query complexity.

---

## Shared vs Per-Architecture Resources

### Shared (created once, used by all)
- **Storage Account** — one account, one `policies` container
- **AI Foundry Account** — one account, multiple model deployments
- **Resource Group** — all resources in one RG for easy teardown

### Per-Architecture (may be duplicated)
- **AI Search Index** — one index per architecture/configuration
- **Search Indexer** — one indexer per index
- **Search Skillset** — one skillset per index (different chunking/embedding)
- **Cosmos DB Account** — only for GraphRAG
- **Function App** — only for GraphRAG query endpoint
- **Container App** — only for LightRAG (built-in server)

### Teardown Granularity
| Action | What Gets Deleted | What Survives |
|---|---|---|
| Delete an index | Index + indexer + skillset | Search service, other indexes |
| Delete a model deployment | One deployment | AI Foundry account, other deployments |
| Delete Cosmos DB account | All graph data | Everything else |
| Delete Function App | Function code + config | Everything else |
| Delete Container App | LightRAG server + config | Everything else |
| Delete resource group | **EVERYTHING** | Nothing |

---

## Skill Files Reference

| Skill File | Covers |
|---|---|
| [azure-ai-search.md](../reference/skills/azure-ai-search.md) | Index creation, vector/hybrid config, query API, Python SDK |
| [azure-ai-search-agentic.md](../reference/skills/azure-ai-search-agentic.md) | Knowledge Bases API, agentic retrieval, query planning |
| [azure-ai-foundry.md](../reference/skills/azure-ai-foundry.md) | AI Services account, model deployments, Bicep, Python SDK |
| [azure-indexer-pipeline.md](../reference/skills/azure-indexer-pipeline.md) | Indexers, skillsets, chunking, integrated vectorization |
| [azure-blob-storage.md](../reference/skills/azure-blob-storage.md) | Storage account, blob upload, managed identity, data source |
| [azure-cosmos-db.md](../reference/skills/azure-cosmos-db.md) | Historical Cosmos patterns and retirement context |
| [azure-functions.md](../reference/skills/azure-functions.md) | Function patterns retained as reference, not current topology |
| [azure-bicep-iac.md](../reference/skills/azure-bicep-iac.md) | Deployment order, Bicep modules, role assignment patterns |
| [embedding-models.md](../reference/skills/embedding-models.md) | Model comparison, deployment, vectorizer config |
| [graphrag-lightrag.md](../reference/skills/graphrag-lightrag.md) | GraphRAG/LightRAG indexing, querying, Azure integration |
