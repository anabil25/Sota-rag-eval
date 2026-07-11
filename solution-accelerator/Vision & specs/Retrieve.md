**Retrieve**

_Eval-driven retrieval architecture selection. Stop guessing which search pipeline works — measure it._

Solution Accelerator Concept · March 2026

---

# The problem this solves

Building a retrieval system for a domain-specific corpus today requires two types of expertise that rarely coexist: deep knowledge of the domain (what questions users actually ask) and deep knowledge of the retrieval landscape (which architecture answers those questions best).

The retrieval landscape is not simple. The options span keyword search, single-vector, multi-vector, hybrid, hybrid+reranker, agentic retrieval, GraphRAG, and LightRAG — each with different embedding models, chunking strategies, and cost profiles. The research has opinions on what works, but "works" is corpus-dependent. A government benefits manual with dense cross-references between policies behaves differently than a product FAQ or a legal contract library.

No existing tool lets you answer the only question that matters: **which retrieval architecture works best for _my_ documents, _my_ users' questions, at a cost I can justify?**

Teams today either pick an architecture based on blog posts and hope, or spend weeks building and benchmarking multiple options manually. Most ship without ever measuring retrieval quality. Retrieve eliminates that by making the entire workflow — ingest, generate evaluation questions, provision architectures, measure, compare, keep the winner — a single guided process.

# What Retrieve is

Retrieve is a solution accelerator that takes a document corpus through a complete eval-driven architecture selection pipeline. It is built around four principles:

**Eval-first.** Before you build anything, you need to know what "good" looks like. Retrieve generates a golden evaluation set from your corpus, lets subject matter experts curate it by category, and uses it to objectively score every configuration you test.

**Compare, don't guess.** Whether you're comparing entire architectures or toggling individual components within a SOTA pipeline, every decision is backed by measured scores on your corpus.

**Opinionated defaults, full customizability.** Retrieve pre-selects the architectures, models, and components that research supports, with a directional cost/accuracy/latency guide so you know what you're getting into. But every choice is overridable — add architectures, swap models, toggle components, adjust the eval set.

**Infrastructure lifecycle management.** Retrieve provisions Azure resources for each configuration under test, runs evaluations, and tears down everything you don't keep. You pay for experiments only while they're running.

# Two evaluation modes

Retrieve supports two distinct modes for different decision points. Both share the same ingestion and golden eval set — the difference is what they evaluate.

## Test Mode — "Which architecture?"

The full multi-architecture comparison flow. Provision multiple fundamentally different retrieval architectures (keyword, hybrid, GraphRAG, etc.), run the golden eval set against each one, compare scores side by side, pick the winner, tear down the rest.

Use Test Mode when you're starting from scratch and need to determine which class of retrieval architecture fits your corpus and use case.

## SOTA Eval Mode — "Which knobs matter within the right architecture?"

For a given use case, Retrieve recommends a SOTA retrieval path — a specific architecture with a defined set of components. Instead of comparing across architectures, SOTA Eval Mode lets you evaluate variations *within* that path by toggling individual components on and off.

For example, if the SOTA path for a government policy corpus is `Hybrid (keyword + vector) → Semantic Reranker → Cross-Encoder`, SOTA Eval Mode runs the golden set against every meaningful combination:

| Configuration | Semantic Reranker | Cross-Encoder | Late Chunking | MRR@10 | nDCG@10 | Δ vs Full |
|---|---|---|---|---|---|---|
| Full SOTA path | ✓ | ✓ | ✓ | 0.78 | 0.82 | — |
| No cross-encoder | ✓ | ✗ | ✓ | 0.71 | 0.76 | -0.06 |
| No semantic reranker | ✗ | ✓ | ✓ | 0.68 | 0.74 | -0.08 |
| No late chunking | ✓ | ✓ | ✗ | 0.74 | 0.79 | -0.03 |
| Bare hybrid (no extras) | ✗ | ✗ | ✗ | 0.59 | 0.65 | -0.17 |

This tells you exactly what each component is worth. If the semantic reranker adds +0.08 nDCG but doubles your latency and cost, you can make that call with evidence. If late chunking only adds +0.03, maybe fixed chunking is good enough.

The components available for toggling depend on the SOTA path. Examples:

| Component | Toggle | What You're Testing |
|---|---|---|
| Azure AI Search semantic reranker | on / off | Is the built-in L2 reranker worth enabling? |
| Cross-encoder reranker | on / off / swap model | Does a dedicated reranker justify the latency? |
| Late chunking vs fixed chunking | swap | Does context-preserving chunking improve scores? |
| Embedding model | swap | text-embedding-3-small vs 3-large vs BGE-M3 |
| Chunk size | 256 / 512 / 1024 | Optimal granularity for this corpus |
| RRF fusion weights | adjust | Tuning dense vs sparse balance |
| Query expansion | on / off | Does LLM-assisted query rewriting help? |

**SOTA paths are use-case specific.** Retrieve will ship with pre-defined SOTA paths for common use cases (to be defined), each representing the research-backed recommended pipeline for that workload type. Users can also define custom paths.

### How the two modes interact

A typical workflow uses both modes in sequence:

1. **Test Mode first** — run a broad architecture comparison to narrow down the class (e.g., "hybrid beats keyword and GraphRAG is overkill for our corpus")
2. **SOTA Eval Mode second** — within the winning architecture class, run component-level evaluation to find the optimal configuration (e.g., "hybrid + semantic reranker + late chunking, but skip the cross-encoder — it only adds 0.02 and costs 3x more")

Both modes store results in the same SQLite database, so you have a unified iteration history across architecture-level and component-level decisions.

# How it works

## End-to-end flow

```
┌──────────────────────────────────────────────────────┐
│  1. INGEST                                           │
│  Copilot-assisted scraping / conversion              │
│  Raw source → structured Markdown with frontmatter   │
└────────────────────┬─────────────────────────────────┘
                     │
                     ▼
┌──────────────────────────────────────────────────────┐
│  2. GOLDEN EVAL SET                                  │
│  Auto-generate questions via Copilot SDK              │
│  Categorize → SME curation UI → finalized eval set   │
└────────────────────┬─────────────────────────────────┘
                     │
                     ▼
┌──────────────────────────────────────────────────────┐
│  3. SELECT MODE                                      │
│                                                      │
│  ┌─────────────────┐    ┌──────────────────────────┐ │
│  │  TEST MODE      │    │  SOTA EVAL MODE          │ │
│  │  Compare across │    │  Optimize within a       │ │
│  │  architectures  │    │  recommended SOTA path   │ │
│  └────────┬────────┘    └────────────┬─────────────┘ │
│           │                          │               │
└───────────┼──────────────────────────┼───────────────┘
            │                          │
     ┌──────▼──────┐           ┌───────▼──────┐
     │ 3a. Review  │           │ 3b. Review   │
     │ architecture│           │ SOTA path    │
     │ × model     │           │ Toggle       │
     │ matrix      │           │ components   │
     │ ($/★ table) │           │ on/off       │
     └──────┬──────┘           └───────┬──────┘
            │                          │
            ▼                          ▼
┌──────────────────────────────────────────────────────┐
│  4. PROVISION & INDEX                                │
│  Spin up Azure resources per configuration           │
│  Upload corpus, build indexes                        │
└────────────────────┬─────────────────────────────────┘
                     │
                     ▼
┌──────────────────────────────────────────────────────┐
│  5. EVALUATE & COMPARE                               │
│  Run golden set through each configuration           │
│  Score: Recall@k, MRR@10, nDCG@10                    │
│  Test Mode: per-architecture dashboard               │
│  SOTA Mode: per-component delta table                │
│  Results stored in SQLite for iteration history      │
└────────────────────┬─────────────────────────────────┘
                     │
                     ▼
┌──────────────────────────────────────────────────────┐
│  6. SELECT & TEAR DOWN                               │
│  Keep winning configuration(s)                       │
│  Tear down everything else                           │
│  Production-ready retrieval endpoint                 │
└──────────────────────────────────────────────────────┘
```

---

## Phase 1: Ingest

Copilot-assisted ingestion converts a raw policy source (website, PDF library, SharePoint, file share) into structured Markdown files with YAML frontmatter. The ingestion pipeline:

- Discovers document structure (TOC, site map, file system)
- Fetches and converts each page/document to clean Markdown
- Extracts metadata: document ID, title, parent section, source URL
- Identifies cross-references between documents
- Produces a corpus ready for any downstream indexing strategy

The output is a local directory of Markdown files — format-agnostic and reusable across all architectures.

## Phase 2: Golden evaluation set

The golden eval set is the foundation everything else is measured against. Retrieve generates it in three steps:

### Step 1 — Synthetic generation

Using the Copilot SDK, Retrieve reads the ingested corpus and generates realistic questions that the documents answer. Questions are automatically categorized by type:

- **Direct lookup** — "What form do I use to apply for SNAP?"
- **Process / procedure** — "How long do I have to process an expedited application?"
- **Eligibility determination** — "Is a 19-year-old full-time student eligible for SNAP?"
- **Cross-document reasoning** — "If a client reports DV, what confidentiality rules apply and what notices must I send?"
- **Edge cases / exceptions** — "Can a fee agent conduct a recertification interview?"

Each question is paired with the ground-truth document chunk(s) that answer it.

### Step 2 — SME curation

Subject matter experts review the generated eval set through a chat-based curation interface. This is not question-by-question editing — it operates at the category level:

> *We generated 150 eval questions across these categories:*
>
> | Category | Count | Examples |
> |---|---|---|
> | Direct lookup | 34 | "What form do I use to apply for SNAP?" |
> | Process / procedure | 28 | "How long do I have to process an expedited application?" |
> | Cross-document reasoning | 22 | "If a client reports DV, what confidentiality rules apply?" |
> | Verification requirements | 41 | "What documents can I accept for citizenship verification?" |
> | Edge cases / exceptions | 25 | "Can a fee agent conduct a recertification interview?" |
>
> SME feedback: *"More cross-document reasoning questions, fewer direct lookups, add a category for fraud referrals, more questions like the DV one."*

Retrieve regenerates / rebalances based on the category-level steering. SMEs can also view the full list and flag individual questions. The goal is a curated set that represents what real users actually ask — not what an LLM thinks they might ask.

### Step 3 — Finalization

The curated eval set is saved as a versioned artifact. Every evaluation run references a specific version of the golden set, so you can track how architecture changes affect scores on the same questions over time.

## Phase 3: Mode selection & configuration

After building the golden eval set, the user selects an evaluation mode.

### Test Mode — Architecture selection

Before provisioning anything, Retrieve presents a directional overview of the available retrieval architectures with ★/$ indicators for expected accuracy, cost, and latency:

| Architecture | Expected Accuracy | Cost | Latency | Best For |
|---|---|---|---|---|
| Keyword only | ★★ | $ | ★★★★★ | Exact policy lookups, known terminology |
| Single vector | ★★★ | $$ | ★★★★ | Semantic similarity, paraphrased questions |
| Hybrid (keyword + vector) | ★★★★ | $$ | ★★★★ | General-purpose, covers both retrieval modes |
| Hybrid + reranker | ★★★★½ | $$$ | ★★★ | High-precision ranking on ambiguous queries |
| Multi-vector (BGE-M3) | ★★★★½ | $$$ | ★★★ | Dense + sparse + token-level matching in one model |
| Agentic retrieval | ★★★★★ | $$$$ | ★★ | Multi-hop, "depends on X and Y" questions |
| GraphRAG | ★★★★★ | $$$$$ | ★ | Cross-document reasoning, relationship traversal |
| LightRAG | ★★★★½ | $$$$ | ★★ | Graph-augmented retrieval, lighter than full GraphRAG |

These are directional estimates based on research benchmarks — not guarantees. The entire point of the accelerator is to replace these estimates with measured scores on your corpus.

**Embedding model selection.** For architectures that use vector search, Retrieve presents a model comparison table:

| Model | Dimensions | MTEB Avg | Cost / 1M tokens | Latency (p50) | Notes |
|---|---|---|---|---|---|
| text-embedding-3-small | 1536 | 62.3 | $0.02 | 12ms | Cheapest Azure-native option |
| text-embedding-3-large | 3072 | 64.6 | $0.13 | 18ms | Higher fidelity, still fast |
| BGE-M3 | 1024 | 66.1 | Self-hosted | 25ms | Dense + sparse + multi-vector in one pass |
| Cohere embed-v3 | 1024 | 64.5 | $0.10 | 15ms | Strong multilingual |

Users can select which architectures and models to evaluate, or accept the recommended defaults. Advanced users can add custom configurations.

### SOTA Eval Mode — Component-level optimization

Instead of comparing across architectures, SOTA Eval Mode starts from a recommended SOTA path for the use case and lets the user evaluate variations within it.

Retrieve recommends a path based on the corpus characteristics observed during ingestion (document count, cross-reference density, average document length, domain). The user sees the full SOTA path with all its components, and can toggle each one on/off to create evaluation variants:

**Example: Government benefits policy corpus → Recommended SOTA path**

```
Hybrid retrieval (keyword + vector)
  → Azure AI Search semantic reranker
  → Cross-encoder reranker (bge-reranker-v2-m3)
  → Late chunking (512 tokens, 64 overlap)
  → Embedding: text-embedding-3-large
```

**Component toggles the user can select:**

| # | Component | Options | Default |
|---|---|---|---|
| 1 | Semantic reranker | on / off | on |
| 2 | Cross-encoder reranker | on / off / swap to Rank1 | on |
| 3 | Chunking strategy | late chunking / fixed 512 / fixed 1024 | late chunking |
| 4 | Embedding model | text-embedding-3-small / 3-large / BGE-M3 | 3-large |
| 5 | Chunk size | 256 / 512 / 1024 | 512 |
| 6 | Query expansion | on / off | off |
| 7 | RRF fusion weights | default / dense-heavy / sparse-heavy | default |

Retrieve generates all selected combinations (or a smart subset if the matrix is large) and provisions each as a separate index configuration. The evaluation phase then scores each variant and shows the per-component delta — what each toggle is worth in measured retrieval quality.

## Phase 4: Provision & index

For each selected architecture, Retrieve provisions the required Azure resources via Bicep/IaC:

| Architecture | Resources Created |
|---|---|
| Keyword only | AI Search (free/basic SKU) |
| Single vector | AI Search + Azure OpenAI (embedding deployment) |
| Hybrid | AI Search + Azure OpenAI (embedding deployment) |
| Hybrid + reranker | AI Search + Azure OpenAI (embedding + reranker) |
| Multi-vector (BGE-M3) | AI Search + container instance (BGE-M3 model server) |
| Agentic retrieval | AI Search + Azure OpenAI + Azure Function (orchestrator) |
| GraphRAG | AI Search + Cosmos DB + Azure Functions + Azure OpenAI |
| LightRAG | AI Search + Azure OpenAI + graph store |

The corpus is uploaded and indexed into each architecture's resources. All provisioning uses managed identity — no keys.

## Phase 5: Evaluate & compare

Retrieve runs the golden eval set through every provisioned configuration using the Copilot SDK and computes standard retrieval metrics. The dashboard adapts to the evaluation mode.

### Test Mode — Architecture comparison dashboard

| Architecture | Recall@5 | Recall@10 | MRR@10 | nDCG@10 | Avg Latency | Est. Monthly Cost |
|---|---|---|---|---|---|---|
| Keyword only | 0.42 | 0.55 | 0.33 | 0.38 | 8ms | $70 |
| Single vector | 0.61 | 0.72 | 0.48 | 0.54 | 45ms | $180 |
| Hybrid | 0.74 | 0.83 | 0.59 | 0.65 | 52ms | $190 |
| Hybrid + reranker | 0.74 | 0.83 | 0.71 | 0.78 | 120ms | $280 |
| Multi-vector (BGE-M3) | 0.78 | 0.87 | 0.68 | 0.75 | 90ms | $320 |
| GraphRAG | 0.81 | 0.89 | 0.74 | 0.82 | 650ms | $850 |

### SOTA Eval Mode — Component delta dashboard

| Configuration | Sem. Reranker | Cross-Encoder | Chunking | Embedding | MRR@10 | nDCG@10 | Δ nDCG | Latency | Cost |
|---|---|---|---|---|---|---|---|---|---|
| Full SOTA | ✓ | ✓ | late | 3-large | 0.78 | 0.82 | — | 120ms | $280 |
| No cross-encoder | ✓ | ✗ | late | 3-large | 0.71 | 0.76 | -0.06 | 52ms | $190 |
| No sem. reranker | ✗ | ✓ | late | 3-large | 0.68 | 0.74 | -0.08 | 95ms | $240 |
| Fixed chunking | ✓ | ✓ | fixed-512 | 3-large | 0.74 | 0.79 | -0.03 | 118ms | $280 |
| Smaller embedding | ✓ | ✓ | late | 3-small | 0.73 | 0.77 | -0.05 | 105ms | $210 |
| BGE-M3 embedding | ✓ | ✓ | late | BGE-M3 | 0.79 | 0.83 | +0.01 | 130ms | $320 |
| Bare hybrid | ✗ | ✗ | fixed-512 | 3-small | 0.55 | 0.61 | -0.21 | 35ms | $120 |

The Δ column makes the value of each component immediately visible. A user can see that the semantic reranker is worth +0.08 nDCG, the cross-encoder adds +0.06 on top of that, and swapping to BGE-M3 gains +0.01 but adds latency and self-hosting cost. These are the numbers that justify the final configuration.

### Per-category breakdown

Each architecture is also scored per question category, revealing where specific architectures shine or struggle:

| Architecture | Direct Lookup | Process | Cross-Doc Reasoning | Edge Cases |
|---|---|---|---|---|
| Keyword only | 0.65 | 0.40 | 0.12 | 0.30 |
| Hybrid | 0.82 | 0.75 | 0.45 | 0.58 |
| Hybrid + reranker | 0.85 | 0.82 | 0.58 | 0.70 |
| GraphRAG | 0.80 | 0.78 | 0.88 | 0.72 |

This tells you, for example, that GraphRAG is only meaningfully better for cross-document reasoning. If your users mostly ask direct lookup and process questions, hybrid+reranker gets you 95% of the value at a third of the cost.

### Failure analysis

For each architecture, Retrieve surfaces the queries it failed on: the question, the expected document, and the top-ranked wrong document. This diagnoses *why* an architecture missed — vocabulary mismatch, semantic gap, cross-reference the architecture can't traverse.

### Iteration history (SQLite)

Every evaluation run is stored in a local SQLite database:
- Eval set version used
- Architecture configuration (model, chunking, parameters)
- Per-query scores and retrieved documents
- Aggregate metrics
- Timestamp

This lets you go back and review: "On March 5 we ran eval v2 against hybrid with text-embedding-3-large and got MRR 0.71. On March 12 we switched to BGE-M3 and got 0.75. On March 15 we added 20 more cross-doc questions to the eval set and the gap widened to 0.68 vs 0.79."

The iteration history is the audit trail that justifies the final architecture choice — critical for enterprise and government clients.

## Phase 6: Select & tear down

The user reviews the comparison dashboard and selects the architecture(s) to keep. Retrieve:

- Retains the selected resources as production infrastructure
- Tears down all other provisioned resources (indexes, model deployments, databases)
- Outputs a deployment summary: what's running, what it costs, how to connect to it
- Provides the configuration needed to plug the winning retrieval endpoint into a downstream application (Copilot Studio, custom UI, API)

---

# Architecture decisions

## Default model choices and why

Every default is chosen because the research supports it, not because of framework convenience. All defaults are overridable.

| Component | Default | Rationale |
|---|---|---|
| First-stage model | BGE-M3 | Only open model producing dense + sparse + multi-vector in one pass. Eliminates separate model servers for each retrieval mode. |
| Fusion strategy | Reciprocal Rank Fusion | Consistently outperforms score normalization and weighted sum on diverse query types. No tuning required. |
| Reranker | bge-reranker-v2-m3 | Strong BEIR performance, open weights, runs on a single GPU. Swap to Rank1 for reasoning-intensive workloads. |
| Chunking | Late chunking (512 tokens, 64 overlap) | Jina's late chunking preserves cross-chunk context via full-document pooling. Better pronoun/reference resolution than naive fixed-size. |
| Eval generation | Copilot SDK (GPT-4o) | Generates realistic, categorized questions with ground-truth pairings. Local LLM fallback via Ollama. |

## The three-stage retrieval model

The core retrieval pipeline, when fully assembled, maps onto three stages. Not every architecture uses all three — keyword-only uses none of them, single-vector uses only Stage 1. But the stages compose cleanly:

```
┌─────────────────────────────────────────┐
│  Stage 1: First-Stage Retrieval         │
│  Dense / sparse / hybrid / multi-vector │
│  → top-100 candidates                  │
└──────────────┬──────────────────────────┘
               │
               ▼
┌─────────────────────────────────────────┐
│  Stage 2: Cross-Encoder Reranker        │
│  bge-reranker-v2-m3 (default)           │
│  Rank1 (reasoning-intensive swap-in)    │
└──────────────┬──────────────────────────┘
               │
               ▼
┌─────────────────────────────────────────┐
│  Stage 3: Agentic / Graph Layer         │
│  Multi-hop traversal, synthesis         │
│  GraphRAG / LightRAG / custom agent     │
└─────────────────────────────────────────┘
```

## Deployment flexibility

Each component declares a backend interface. Local and cloud backends are interchangeable:

```python
# Fully local — no API dependencies
pipeline = RetrievePipeline.local()

# Cloud reranker, local first-stage
pipeline = RetrievePipeline(
    retriever=LocalBGEM3Retriever(),
    reranker=CohereReranker(api_key=...),
    store=QdrantCloud(url=..., api_key=...)
)

# Azure enterprise configuration
pipeline = RetrievePipeline.azure(
    search_endpoint=...,
    openai_reranker=True
)
```

---

# Explicit scope

## What Retrieve is

- A solution accelerator that selects the right retrieval architecture through measurement, not guesswork
- An eval-driven pipeline: ingest → generate golden set → provision architectures → measure → compare → ship
- A tool that tells you how good your retrieval is, broken down by architecture, question category, and failure mode
- An infrastructure lifecycle manager: spin up experiments, keep the winner, tear down the rest
- A local-first tool with a UI, SQLite history, and full customizability

## What Retrieve is not

- A RAG framework — it does not manage prompts, conversation history, or LLM output
- An agent framework — the agentic layer is one architecture option, not a built-in orchestrator
- A vector database — it uses and abstracts over existing stores
- A fine-tuning platform — domain adaptation is a planned later module, triggered by eval evidence

---

# How it compares

|  | Retrieve | LangChain / LlamaIndex | Haystack | Azure AI Search (alone) |
|---|---|---|---|---|
| Multi-architecture comparison | ✓ | ✗ | ✗ | ✗ |
| Golden eval set generation | ✓ | ✗ | ✗ | ✗ |
| SME curation (category-level) | ✓ | ✗ | ✗ | ✗ |
| Per-stage / per-architecture eval | ✓ | ✗ | Limited | ✗ |
| Failure diagnostics | ✓ | ✗ | ✗ | ✗ |
| Infrastructure provisioning | ✓ (Azure IaC) | ✗ | ✗ | Manual |
| Iteration history (SQLite) | ✓ | ✗ | ✗ | ✗ |
| Teardown of unused resources | ✓ | N/A | N/A | Manual |
| SOTA defaults out of box | ✓ | ✗ (you choose) | ✗ (you choose) | Partial |
| Local + cloud flexibility | ✓ | ✓ | ✓ | Cloud only |
| GraphRAG / LightRAG as options | ✓ | Possible but manual | ✗ | ✗ |

---

# Roadmap

## v0.1 — Core pipeline & eval generation

- Corpus ingestion: Markdown with YAML frontmatter
- Golden eval set generation via Copilot SDK (categorized, with ground-truth pairings)
- SQLite schema for eval set versioning and run history
- CLI: `retrieve ingest`, `retrieve eval generate`, `retrieve eval curate`

## v0.2 — Architecture comparison engine

- Architecture registry: keyword, single-vector, hybrid, hybrid+reranker, multi-vector
- Embedding model registry with $/★ metadata
- Azure resource provisioning via Bicep templates per architecture
- Corpus upload and indexing for each provisioned architecture
- CLI: `retrieve provision`, `retrieve index`

## v0.3 — Evaluation runner & dashboard

- Run golden set against all provisioned architectures
- Per-architecture and per-category scoring (Recall@k, MRR@10, nDCG@10)
- Failure analysis per architecture
- Comparison dashboard (HTML/web UI)
- Iteration history stored in SQLite
- CLI: `retrieve eval run`, `retrieve eval compare`

## v0.4 — Curation UI & select/teardown

- Chat-based golden set curation interface (category-level steering)
- Architecture selection UI with teardown of unselected resources
- Deployment summary output
- Full web UI wrapping the CLI workflow

## v0.5 — Advanced architectures

- GraphRAG as a provisionable architecture (Cosmos DB + Azure Functions + AI Search)
- LightRAG as a provisionable architecture
- Agentic retrieval (multi-hop Azure Function orchestrator)
- Custom architecture plugin interface

## v0.6 — Domain adaptation

- Eval-triggered fine-tuning recommendation
- Automated LoRA fine-tuning of retriever on corpus + synthetic labels
- Before/after eval comparison on same golden set
- Fine-tuned model versioning and rollback

---

# Why open source

Open source is not a distribution channel for Retrieve — it is the distribution strategy. The value of a retrieval evaluation accelerator compounds with adoption: more corpora surface edge cases in the eval generation, more architecture comparisons validate (or challenge) the directional ★/$ ratings, and more connectors extend the set of provisionable backends.

The goal is for Retrieve to become the standard answer to "how do I know which retrieval architecture to use?" — the tool people reach for before they commit to building anything.

Enterprise teams that adopt Retrieve are the same teams that need deployment support, fine-tuning services, and custom architecture integrations. The accelerator opens those conversations.

github.com/retrieve-ai/retrieve

March 2026