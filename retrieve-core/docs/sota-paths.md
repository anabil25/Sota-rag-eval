# SOTA Paths — Recommended Retrieval Pipelines

Retrieve ships **four pre-built SOTA paths**, each tuned for a specific corpus archetype.
The SOTA Eval Runner (`retrieve eval sota`) iterates over every meaningful toggle
combination and surfaces per-component marginal deltas so you can see exactly
which component earns its cost.

---

## 1. Government Benefits Policy

**Key:** `government-policy`
**Base architecture:** `hybrid-reranker`

**When to use:**
- Government benefits manuals and administrative procedures
- Dense cross-references between numbered policies (§100-3 → §205)
- Caseworker lookup queries and eligibility determination
- Regulatory documents with hierarchical section numbering

**Toggles evaluated:**

| Component | Options | Default | Why |
|---|---|---|---|
| `semantic_reranker` | on, off | on | Measures marginal value of L2 semantic reranking |
| `chunking_strategy` | late_chunking, fixed_512, fixed_1024 | late_chunking | Late chunking preserves cross-reference context |
| `embedding_model` | text-embedding-3-small, text-embedding-3-large, bge-m3 | text-embedding-3-large | Tests cost-accuracy tradeoff across embedding models |
| `chunk_size` | 256, 512, 1024 | 512 | Balances context window vs granularity |
| `query_expansion` | on, off | off | LLM query rewriting for jargon-heavy queries |
| `rrf_weights` | default, dense_heavy, sparse_heavy | default | RRF fusion weight balance |

**Corpus heuristics:** Triggered when `cross_ref_density ≥ 1.0`.

---

## 2. Product Documentation

**Key:** `product-docs`
**Base architecture:** `hybrid-reranker`

**When to use:**
- Product manuals, API documentation, SDK references
- Well-structured standalone pages with clear headings
- Technical content with code examples
- How-to guides and tutorials

**Toggles evaluated:**

| Component | Options | Default | Why |
|---|---|---|---|
| `semantic_reranker` | on, off | on | L2 reranking typically high-value for technical queries |
| `embedding_model` | text-embedding-3-small, text-embedding-3-large | text-embedding-3-small | Smaller model often sufficient for structured docs |
| `chunk_size` | 256, 512, 1024 | 512 | Heading-aligned chunks work well at 512 |
| `query_expansion` | on, off | off | Usually unnecessary for well-structured docs |

**Corpus heuristics:** Triggered when `cross_ref_density < 1.0` and `avg_doc_length ≥ 1500`.

---

## 3. Legal & Contract Corpus

**Key:** `legal-contracts`
**Base architecture:** `hybrid-reranker`

**When to use:**
- Legal documents, contracts, compliance materials
- Long documents with precise legal terminology
- Heavy cross-referencing between clauses and sections
- Queries that require connecting specific provisions

**Toggles evaluated:**

| Component | Options | Default | Why |
|---|---|---|---|
| `semantic_reranker` | on, off | on | Critical for bridging legal terminology to queries |
| `chunking_strategy` | late_chunking, fixed_512, fixed_1024 | late_chunking | Preserves clause context across chunk boundaries |
| `embedding_model` | text-embedding-3-large, bge-m3 | text-embedding-3-large | Legal domain benefits from larger models |
| `chunk_size` | 512, 1024 | 1024 | Larger chunks preserve full clause context |
| `query_expansion` | on, off | on | Bridges formal legal language to natural queries |

**Corpus heuristics:** Triggered when `avg_doc_length ≥ 5000` and `cross_ref_density ≥ 2.0`.

---

## 4. Knowledge Base / FAQ

**Key:** `knowledge-base-faq`
**Base architecture:** `hybrid`

**When to use:**
- FAQ articles, help center content
- Short, self-contained documents
- Minimal cross-references between articles
- Simple factual queries

**Toggles evaluated:**

| Component | Options | Default | Why |
|---|---|---|---|
| `embedding_model` | text-embedding-3-small, text-embedding-3-large | text-embedding-3-small | Small model is cost-effective for short docs |
| `chunk_size` | 256, 512 | 256 | Short docs → shorter chunks |
| `rrf_weights` | default, dense_heavy | default | Tests whether dense retrieval dominates |

**Corpus heuristics:** Triggered when `avg_doc_length < 2000` and `cross_ref_density < 0.5`.

---

## Running SOTA Eval

```bash
# Auto-detect corpus type and run all toggle combinations
retrieve eval sota

# Specify a path explicitly
retrieve eval sota --path government-policy

# Limit the number of variants tested
retrieve eval sota --path legal-contracts --max-variants 20
```

## Output

The SOTA runner produces:

1. **Variant Results Table** — Recall@10, MRR@10, and latency for each toggle combination
2. **Component Delta Table** — Marginal impact of each toggle change vs the defaults
3. **Recommended Configuration** — The toggle combination that maximized Recall@10

## Custom SOTA Paths

To add a custom path, define it in `retrieve-core/src/retrieve/registry/sota_paths.py`:

```python
SOTA_PATHS["my-domain"] = SOTAPath(
    name="My Custom Domain",
    description="Description of corpus characteristics...",
    base_architecture="hybrid-reranker",
    components=[
        ComponentToggle(name="semantic_reranker", options=["on", "off"], default="on"),
        ComponentToggle(name="chunk_size", options=["256", "512", "1024"], default="512"),
    ],
)
```
