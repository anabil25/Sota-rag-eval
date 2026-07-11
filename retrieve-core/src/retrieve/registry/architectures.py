"""Architecture registry — built-in retrieval architectures with directional metadata."""

from __future__ import annotations

from pydantic import BaseModel


class Architecture(BaseModel):
    name: str
    accuracy: str  # ★ rating
    cost: str  # $ rating
    latency: str  # ★ rating (higher = faster)
    best_for: str
    required_azure_resources: list[str]
    description: str = ""
    # Directional estimate for the comparison dashboard. Replaced with measured cost
    # when usage telemetry is available.
    est_monthly_usd: int = 0

    # Which components can be toggled in SOTA eval mode
    toggleable_components: list[str] = []


ARCHITECTURES: dict[str, Architecture] = {
    "keyword": Architecture(
        name="Keyword only",
        accuracy="★★",
        cost="$",
        latency="★★★★★",
        best_for="Exact policy lookups, known terminology",
        required_azure_resources=["storage", "search"],
        description="AI Search keyword-only index. No embeddings.",
        est_monthly_usd=70,
    ),
    "single-vector": Architecture(
        name="Single vector",
        accuracy="★★★",
        cost="$$",
        latency="★★★★",
        best_for="Semantic similarity, paraphrased questions",
        required_azure_resources=["storage", "search", "ai_foundry"],
        est_monthly_usd=180,
    ),
    "hybrid": Architecture(
        name="Hybrid (keyword + vector)",
        accuracy="★★★★",
        cost="$$",
        latency="★★★★",
        best_for="General-purpose, covers both retrieval modes",
        required_azure_resources=["storage", "search", "ai_foundry"],
        toggleable_components=["embedding_model", "chunk_size", "rrf_weights"],
        est_monthly_usd=190,
    ),
    "hybrid-reranker": Architecture(
        name="Hybrid + reranker",
        accuracy="★★★★½",
        cost="$$$",
        latency="★★★",
        best_for="High-precision ranking on ambiguous queries",
        required_azure_resources=["storage", "search", "ai_foundry"],
        toggleable_components=[
            "semantic_reranker",
            "embedding_model",
            "chunk_size",
            "chunking_strategy",
            "rrf_weights",
            "query_expansion",
        ],
        est_monthly_usd=280,
    ),
    "hybrid-llm-enriched": Architecture(
        name="Hybrid + LLM enrichment",
        accuracy="★★★★½",
        cost="$$$",
        latency="★★★",
        best_for="Cross-ref extraction and topic tagging at index time",
        required_azure_resources=["storage", "search", "ai_foundry"],
        toggleable_components=[
            "semantic_reranker",
            "embedding_model",
            "chunk_size",
            "chunking_strategy",
            "rrf_weights",
            "query_expansion",
        ],
        est_monthly_usd=290,
    ),
    "multi-vector": Architecture(
        name="Multi-vector",
        accuracy="★★★★½",
        cost="$$$",
        latency="★★★",
        best_for="Dense, sparse, and token-level retrieval signals",
        required_azure_resources=["storage", "search", "aci"],
        description="Multiple vector representations per chunk; embedding source is configured separately.",
        est_monthly_usd=320,
    ),
    "agentic-kb": Architecture(
        name="Agentic retrieval",
        accuracy="★★★★★",
        cost="$$$$",
        latency="★★",
        best_for="Multi-hop, 'depends on X and Y' questions",
        required_azure_resources=["storage", "search", "ai_foundry"],
        description="LLM-guided query planning and multi-step retrieval over search sources.",
        est_monthly_usd=520,
    ),
    "graphrag": Architecture(
        name="GraphRAG",
        accuracy="★★★★★",
        cost="$$$$$",
        latency="★",
        best_for="Cross-document reasoning, relationship traversal",
        required_azure_resources=["storage", "search", "ai_foundry", "cosmos", "container_apps"],
        est_monthly_usd=850,
    ),
    "lightrag": Architecture(
        name="LightRAG",
        accuracy="★★★★½",
        cost="$$$$",
        latency="★★",
        best_for="Graph-augmented retrieval, lighter than full GraphRAG",
        required_azure_resources=["storage", "search", "ai_foundry", "container_apps", "postgresql"],
        est_monthly_usd=480,
    ),
}


def get_architecture(name: str) -> Architecture:
    if name not in ARCHITECTURES:
        raise ValueError(
            f"Unknown architecture '{name}'. Available: {', '.join(ARCHITECTURES)}"
        )
    return ARCHITECTURES[name]
