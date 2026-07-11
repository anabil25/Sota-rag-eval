# Skill: GraphRAG & LightRAG — Knowledge Graph Retrieval on Azure

> For: Retrieve solution accelerator — deploying and querying GraphRAG/LightRAG as architecture options for cross-document reasoning.
>
> **Source repos:** `graphrag-main/` (v3.0.6, Microsoft), `LightRAG-main/` (HKU)

## When to Use
- Evaluating graph-augmented retrieval architectures in Test Mode
- Corpus has dense cross-references between documents (policy manuals, legal codes, regulatory frameworks)
- Questions require multi-hop reasoning ("If X applies, and X references Y, what does Y say about Z?")
- Standard hybrid search misses cross-document relationships

---

# GraphRAG v3 (Microsoft)

> **CRITICAL:** The skill below is for GraphRAG v3 (March 2026). v3 has a completely different config format from v1/v2. The config uses `completion_models:` and `embedding_models:` with `model_provider:` — NOT the old `llm: type: azure_openai_chat` syntax.

## Architecture
```
Corpus (Markdown files)
  → graphrag index (6-phase pipeline)
    Phase 1: Chunk into text units
    Phase 2: Link documents ↔ text units
    Phase 3: LLM entity/relationship extraction + summarization
    Phase 4: Hierarchical Leiden community detection
    Phase 5: LLM community report generation
    Phase 6: Embedding generation (entities, text units, community reports)
  → Stored in: Cosmos DB / Blob Storage / local parquet
  → Vector embeddings: AI Search / Cosmos DB / local
      
Query modes:
  Global Search → Map-reduce over community reports → Answer
  Local Search  → Entity neighborhood + vector similarity → Answer
  DRIFT Search  → Community-informed iterative exploration → Answer
  Basic Search  → Simple vector RAG over text units (baseline)
```

## Required Azure Resources
| Resource | Purpose | Required |
|---|---|---|
| Azure OpenAI (GPT-4.1) | Entity extraction, community summarization, query synthesis | Yes |
| Azure OpenAI (text-embedding-3-large) | Entity/text unit/community report embeddings | Yes |
| Cosmos DB (NoSQL, Serverless) | Store graph artifacts (entities, relationships, communities) | Production (or use blob/local for eval) |
| Azure Blob Storage | Alternative artifact storage (parquet files) | Dev/eval alternative to Cosmos |
| Azure AI Search | Vector store for embeddings (Local/DRIFT search) | Yes (native adapter) |
| Azure Functions | Query API endpoint | Yes (GraphRAG query is Python-only, needs compute) |

## Installation
```bash
pip install graphrag
# v3 requires Python 3.10+ and uses LiteLLM for model abstraction
```

## Configuration (`settings.yaml` — v3 syntax)

### Azure OpenAI + Cosmos DB + AI Search
```yaml
# LLM Models — v3 uses completion_models / embedding_models blocks
completion_models:
  default_completion_model:
    model_provider: azure
    model: gpt-4.1
    api_base: https://<your-openai>.openai.azure.com/
    api_version: "2024-10-21"
    auth_method: azure_managed_identity   # or api_key
    azure_deployment_name: gpt-41         # only if deployment name ≠ model name

embedding_models:
  default_embedding_model:
    model_provider: azure
    model: text-embedding-3-large
    api_base: https://<your-openai>.openai.azure.com/
    auth_method: azure_managed_identity

# Input — where to read documents from
input:
  type: file
  file_type: text
  base_dir: ../policies

# Output storage — where graph artifacts go
output_storage:
  type: cosmosdb                          # or: blob, file, memory
  connection_string: ${COSMOS_CONNECTION_STRING}
  container_name: graphrag-output
  database_name: graphrag

# Vector store — where embeddings go (used by Local/DRIFT search)
vector_store:
  type: azure_ai_search                  # native adapter!
  url: https://<search-service>.search.windows.net
  audience: https://cognitiveservices.azure.com/.default  # for managed identity
  # api_key: ${AI_SEARCH_API_KEY}        # alternative to managed identity

# Chunking
chunking:
  type: tokens
  size: 1200
  overlap: 100

# Entity extraction
extract_graph:
  completion_model_id: default_completion_model
  entity_types: [organization, person, geo, event, policy, regulation]
  max_gleanings: 1

# Community reports
community_reports:
  completion_model_id: default_completion_model
```

### Indexing Methods
| Method | Command | How | Cost (~300 docs) |
|---|---|---|---|
| **Standard** | `graphrag index --method standard` | Full LLM extraction + summarization | $10-30 |
| **Fast** | `graphrag index --method fast` | NLP entity extraction (no LLM), LLM only for community reports | $2-8 |

### Incremental Updates
```bash
graphrag update --root ./workspace --method standard
# Only processes new/changed documents
```

### Prompt Tuning
```bash
graphrag prompt-tune --root ./workspace --domain "government benefits policy"
# Auto-tunes extraction prompts to your domain
```

## Indexing Pipeline (6 phases)

| Phase | What Happens | LLM Calls? |
|---|---|---|
| 1. Compose TextUnits | Documents → chunks (1200 tokens default, 100 overlap) | No |
| 2. Document Processing | Links documents ↔ text units for provenance | No |
| 3. Graph Extraction | Entity + relationship extraction from each chunk. Subgraph merge. Entity/relationship summarization. | Yes — most expensive phase (~75% of cost) |
| 4. Graph Augmentation | Hierarchical Leiden community detection (via `graspologic-native`) | No |
| 5. Community Summarization | LLM generates report for each community at each hierarchy level | Yes |
| 6. Text Embeddings | Generate vectors for entities, text units, community reports | Yes (embedding model) |

### Output Artifacts
| Artifact | Contents | Used By |
|---|---|---|
| `documents` | Original docs with text unit links | Provenance |
| `text_units` | Chunks with entity/relationship/covariate IDs | Local Search, Basic Search |
| `entities` | Extracted entities (name, type, description, frequency) | All search modes |
| `relationships` | Edges (source, target, description, weight) | Local Search, DRIFT |
| `communities` | Hierarchical community structure | Global Search, DRIFT |
| `community_reports` | LLM-generated summaries per community | Global Search, DRIFT |
| `covariates` | (Optional) Extracted claims | Local Search |

## Query Engine — 4 Search Methods

### Global Search
- **How**: Map-reduce over community reports. Reports batched → LLM rates intermediate responses → top-rated points aggregated → final LLM synthesis.
- **When**: Thematic questions — "What are the main themes in privacy policy?"
- **Params**: `community_level`, `dynamic_community_selection`, `response_type`, `max_context_tokens`

### Local Search
- **How**: Query → extract semantically-related entities (via embedding similarity) → pull entity neighborhood (related entities, relationships, community reports, text units) → LLM synthesis.
- **When**: Entity-specific questions — "What happens when a client reports DV?"
- **Params**: `text_unit_prop`, `community_prop`, `top_k_entities`, `top_k_relationships`, `conversation_history_max_turns`

### DRIFT Search (Dynamic Reasoning and Inference with Flexible Traversal)
- **How**: 3 phases — Primer (compare query vs top-K community reports → initial answer + follow-up questions) → Follow-Up (local search to refine each follow-up, iterative) → Output (hierarchical tree of answers ranked by relevance).
- **When**: Questions needing both broad context and specific detail.
- **Params**: `drift_k_followups: 20`, `primer_folds: 5`, `n_depth: 3`, plus local search sub-params

### Basic Search
- **How**: Simple vector RAG over text units. No knowledge graph.
- **When**: Baseline comparison against other modes.

## Programmatic Python API (v3)
```python
import graphrag.api as api
from graphrag.config.load_config import load_config
from pathlib import Path

config = load_config(root_dir=Path("./workspace"))

# Indexing
results = await api.build_index(config=config, method="standard")

# Global Search
response, context = await api.global_search(
    config=config,
    entities=entities_df,
    communities=communities_df,
    community_reports=reports_df,
    community_level=2,
    dynamic_community_selection=False,
    response_type="Multiple Paragraphs",
    query="What are the main privacy policies?",
)

# Local Search
response, context = await api.local_search(
    config=config,
    entities=entities_df,
    communities=communities_df,
    community_reports=reports_df,
    text_units=text_units_df,
    relationships=relationships_df,
    covariates=None,
    community_level=2,
    response_type="Multiple Paragraphs",
    query="What happens when a client reports DV?",
)

# Streaming
async for chunk in api.local_search_streaming(config=config, ...):
    print(chunk, end="")
```

## CLI Commands
| Command | Purpose |
|---|---|
| `graphrag init --root PATH` | Generate settings.yaml, .env, prompts/ |
| `graphrag index --root PATH --method [standard\|fast]` | Build knowledge graph |
| `graphrag update --root PATH` | Incremental update |
| `graphrag query "question" --method [global\|local\|drift\|basic]` | Query the index |
| `graphrag prompt-tune --root PATH --domain "..."` | Auto-tune prompts to domain |

## Azure-Native Dependencies
```
azure-identity~=1.25
azure-storage-blob~=12.24
azure-search-documents~=11.6
azure-cosmos~=4.9
```

---

# LightRAG (HKU)

> LightRAG is a fundamentally different architecture from GraphRAG: **no community detection, no community reports**. The graph is entity-relation only. It's simpler, cheaper, and has more storage backend options — but lacks the hierarchical reasoning that communities provide.

## Architecture
```
Corpus (text files)
  → lightrag.insert() (LLM entity/relationship extraction per chunk)
    → Entity nodes + relationship edges in graph store
    → Entity/relation/chunk embeddings in vector store
    → Chunks in KV store
    
Query modes (6 total):
  naive   → Vector search on chunks only (standard RAG)
  local   → Query keywords → entity vector match → entity neighborhood from graph → LLM
  global  → Query keywords → relationship vector match → connected entities → LLM
  hybrid  → local + global combined
  mix     → KG retrieval + vector chunk retrieval + optional reranker → LLM (RECOMMENDED)
  bypass  → Direct LLM, no retrieval
```

## Installation
```bash
pip install lightrag-hku
# Or with server mode:
pip install "lightrag-hku[api]"
```

## Storage Backends (7+ options each)

### Graph Storage
| Backend | Implementation | Azure Option |
|---|---|---|
| NetworkX (default) | `NetworkXStorage` | Local files |
| Neo4j | `Neo4JStorage` | Azure-hosted Neo4j |
| PostgreSQL (Apache AGE) | `PGGraphStorage` | Azure Database for PostgreSQL |
| MongoDB | `MongoGraphStorage` | Cosmos DB for MongoDB vCore |
| Memgraph | `MemgraphStorage` | — |
| OpenSearch | `OpenSearchGraphStorage` | Azure OpenSearch? |

### Vector Storage
| Backend | Implementation | Azure Option |
|---|---|---|
| nano-vectordb (default) | `NanoVectorDBStorage` | Local files |
| PostgreSQL (pgvector) | `PGVectorStorage` | Azure Database for PostgreSQL |
| Milvus | `MilvusVectorDBStorage` | Azure-hosted Milvus |
| Qdrant | `QdrantVectorDBStorage` | Azure-hosted Qdrant |
| Faiss | `FaissVectorDBStorage` | Local |
| MongoDB Atlas | `MongoVectorDBStorage` | Cosmos DB for MongoDB vCore |
| OpenSearch | `OpenSearchVectorDBStorage` | — |

### KV Storage
| Backend | Implementation | Azure Option |
|---|---|---|
| JSON files (default) | `JsonKVStorage` | Local |
| PostgreSQL | `PGKVStorage` | Azure Database for PostgreSQL |
| Redis | `RedisKVStorage` | Azure Cache for Redis |
| MongoDB | `MongoKVStorage` | Cosmos DB for MongoDB vCore |
| OpenSearch | `OpenSearchKVStorage` | — |

### IMPORTANT: No Native Azure AI Search or Cosmos DB (NoSQL) Adapter
LightRAG does NOT have adapters for Azure AI Search or Cosmos DB for NoSQL. The closest Azure-compatible options are:
- **Azure Database for PostgreSQL Flexible Server** (uses PG* adapters for all 4 storage types — pgvector for vectors, Apache AGE for graph). Note: **Cosmos DB for PostgreSQL has been retired** — use PostgreSQL Flexible Server instead.
- **Cosmos DB for MongoDB vCore** (uses Mongo* adapters). Must use vCore tier, not RU-based — only vCore supports Atlas-compatible vector search.

## Azure OpenAI Configuration

### Server mode (`.env`)
```bash
LLM_BINDING=azure_openai
LLM_BINDING_HOST=https://<your-openai>.openai.azure.com/
LLM_BINDING_API_KEY=your_api_key
LLM_MODEL=gpt-41-deployment
AZURE_OPENAI_API_VERSION=2024-08-01-preview

EMBEDDING_BINDING=azure_openai
EMBEDDING_BINDING_HOST=https://<your-openai>.openai.azure.com/
EMBEDDING_BINDING_API_KEY=your_api_key
EMBEDDING_MODEL=text-embedding-3-large-deployment
AZURE_EMBEDDING_API_VERSION=2024-08-01-preview
```

### Python SDK mode
```python
from lightrag import LightRAG, QueryParam
from lightrag.llm.azure_openai import azure_openai_complete_if_cache, azure_openai_embed

rag = LightRAG(
    working_dir="./lightrag-workspace",
    llm_model_func=azure_openai_complete_if_cache,
    llm_model_name="gpt-41-deployment",
    llm_model_kwargs={
        "api_key": os.environ["AZURE_OPENAI_API_KEY"],
        "azure_endpoint": "https://<your-openai>.openai.azure.com/",
        "api_version": "2024-10-21",
    },
    embedding_func=EmbeddingFunc(
        embedding_dim=3072,
        max_token_size=8191,
        func=lambda texts: azure_openai_embed(
            texts,
            model="text-embedding-3-large-deployment",
            api_key=os.environ["AZURE_OPENAI_API_KEY"],
            azure_endpoint="https://<your-openai>.openai.azure.com/",
            api_version="2024-10-21",
        ),
    ),
)

# CRITICAL: Must initialize storages before use
await rag.initialize_storages()

# Insert documents
for md_file in Path("policies").rglob("*.md"):
    await rag.ainsert(md_file.read_text())

# Query — 'mix' is the recommended default mode
result = await rag.aquery(
    "What confidentiality rules apply when a client reports DV?",
    param=QueryParam(mode="mix")
)
```

## Query Modes (6 total)

| Mode | How It Works | When to Use |
|---|---|---|
| `naive` | Vector search on chunks only. Standard RAG. No knowledge graph. | Baseline comparison |
| `local` | Extract keywords → find matching entities via vector DB → retrieve entity neighborhood from graph → LLM synthesis | Entity-specific questions |
| `global` | Extract keywords → find matching relationships via vector DB → retrieve connected entities → LLM synthesis | Relationship-focused questions |
| `hybrid` | Combines local + global, merges results | Balanced retrieval |
| `mix` | KG retrieval (entities + relations) AND vector chunk retrieval → optional reranker → LLM synthesis. **Recommended default.** | Best overall quality |
| `bypass` | Skip retrieval, direct LLM | No RAG needed |

### Reranker Support
LightRAG supports rerankers (Cohere, Jina, Aliyun, vLLM-compatible) to improve result quality in `mix` mode.

### Query Parameters (`QueryParam`)
- `mode` — query mode
- `top_k` — entities/relations to retrieve (default 60)
- `chunk_top_k` — text chunks to retrieve (default 20)
- `response_type` — "Multiple Paragraphs", "Bullet Points", etc.
- `stream` — streaming output
- `enable_rerank` — toggle reranking
- `conversation_history` — multi-turn context
- `only_need_context` / `only_need_prompt` — debugging/inspection

## Built-in Server & Web UI
LightRAG ships with a **FastAPI server** and **React 19 Web UI**:
```bash
lightrag-server --host 0.0.0.0 --port 9621
# Includes: document upload, KG visualization, query interface, API (Ollama-compatible)
```

Docker deployment:
```bash
docker compose up -d  # minimal: just LightRAG server
# OR
docker compose -f docker-compose-full.yml up -d  # full stack: LightRAG + Neo4j + Milvus + PostgreSQL
```

This **eliminates the need for a custom Azure Function wrapper** for LightRAG — deploy the Docker image to Azure Container Apps instead.

## Additional Capabilities
- **Document deletion** with automatic KG regeneration
- **Custom KG insertion** — `insert_custom_kg()` for importing pre-built knowledge
- **Entity/relation CRUD** — `create_entity()`, `edit_entity()`, `create_relation()`, etc.
- **Citation support** — file path tracing back to source documents
- **RAGAS evaluation** and **Langfuse tracing** integration
- **Workspace isolation** — data isolation between multiple LightRAG instances

---

# GraphRAG vs LightRAG — Accurate Comparison

| Aspect | GraphRAG v3 | LightRAG |
|---|---|---|
| **Entity extraction** | Multi-pass with LLM gleaning (standard) or NLP-only (fast) | Single-pass LLM with configurable gleaning |
| **Community detection** | Yes — Hierarchical Leiden algorithm | **No** — entity-relation graph only |
| **Community reports** | Yes — LLM-generated summaries per community | **No** |
| **Query modes** | Global, Local, DRIFT, Basic (4) | Naive, Local, Global, Hybrid, Mix, Bypass (6) |
| **Reranker support** | No built-in | Yes (Cohere, Jina, vLLM) |
| **Storage backends** | File, Blob, Cosmos DB, Memory (4) | NetworkX, Neo4j, PostgreSQL, MongoDB, Milvus, Qdrant, Faiss, Redis, OpenSearch (7+) |
| **Azure AI Search adapter** | Yes (native vector store) | No |
| **Cosmos DB adapter** | Yes (native artifact storage) | No (Mongo wire protocol only) |
| **Built-in web UI** | Unified search app (basic) | Full React UI with KG visualization |
| **Built-in server** | CLI only | FastAPI server + Ollama-compatible API |
| **Indexing cost (~300 docs)** | Standard: $10-30, Fast: $2-8 | $3-10 (GPT-4o-mini) / $10-25 (GPT-4.1) |
| **Best for** | Hierarchical thematic reasoning, community-level insights | Entity-relationship traversal, reranked retrieval |
| **Config format** | `settings.yaml` (complex, many options) | Constructor params + `.env` (simpler) |
| **Package** | `pip install graphrag` | `pip install lightrag-hku` |

---

# Retrieve Integration

## Test Mode — GraphRAG as Architecture Option
1. Provision: AI Foundry + Cosmos DB (Serverless) + AI Search + Functions
2. Index: Run `graphrag index --method standard` (or `fast` for cheaper eval)
3. Deploy: Function app wrapping `graphrag.api.local_search` / `global_search`
4. Eval: Run golden set through the Function endpoint
5. Teardown: Delete Cosmos DB + Function App (keep AI Search/Foundry if shared)

## Test Mode — LightRAG as Architecture Option
1. Provision: AI Foundry + Azure Database for PostgreSQL Flexible Server (or Container Apps with local storage for eval)
2. Index: Run `rag.ainsert()` for all corpus documents
3. Deploy: LightRAG Docker image on Azure Container Apps (built-in server, no Function needed)
4. Eval: Run golden set through the LightRAG server API
5. Teardown: Delete Container App + PostgreSQL Flexible Server (keep Foundry if shared)

## SOTA Eval Mode — Not Applicable
GraphRAG and LightRAG are fundamentally different architectures, not component toggles. They appear in Test Mode comparisons, not SOTA eval toggles.

---

# Key Gotchas

1. **GraphRAG v3 config is totally different from v1/v2** — `completion_models:` and `embedding_models:` blocks, `model_provider: azure`, NO `type: azure_openai_chat`. The v1/v2 syntax will silently fail.
2. **GraphRAG indexing is slow and expensive** — Standard method: ~30 min, $10-30 for 300 docs. Use `--method fast` for eval ($2-8) or `graphrag prompt-tune` for better extraction quality.
3. **LightRAG `await rag.initialize_storages()` is mandatory** — Must be called after constructing `LightRAG()`. Without it, the system will error.
4. **LightRAG has no Cosmos DB (NoSQL) or AI Search adapter** — For Azure, use **PostgreSQL Flexible Server** (all 4 storage types via PG* adapters, NOT Cosmos DB for PostgreSQL which is retired) or **Cosmos DB for MongoDB vCore** (Mongo* adapters, must be vCore tier).
5. **LightRAG's recommended query mode is `mix`** — not `hybrid`. `mix` combines KG + vector chunk retrieval with optional reranking.
6. **GraphRAG has a native AI Search vector store adapter** — `type: azure_ai_search` in `vector_store:` config. No custom code needed.
7. **LightRAG ships its own server** — No Azure Function wrapper needed. Deploy the Docker image to Container Apps.
8. **Entity extraction quality varies by domain** — For policy content, consider `graphrag prompt-tune --domain "government benefits policy"` or customizing `entity_types` to include `policy`, `regulation`, `program`, `form`.
9. **Version pinning is critical** — Both projects evolve rapidly. Pin in requirements.txt.
10. **For eval-only GraphRAG runs** — Use `output_storage: type: file` (local parquet) instead of Cosmos DB. Load DataFrames directly. Faster setup, no Cosmos cost.
