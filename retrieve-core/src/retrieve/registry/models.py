"""Model registries — embedding models and rerankers with directional metadata."""

from __future__ import annotations

from pydantic import BaseModel

# ── Embedding models ──────────────────────────────────────────────────


class EmbeddingModel(BaseModel):
    name: str
    dimensions: int
    mteb_avg: float
    cost_per_1m: str
    latency_p50: str
    notes: str
    provider: str  # azure_openai | self_hosted | cohere


EMBEDDING_MODELS: dict[str, EmbeddingModel] = {
    "text-embedding-3-small": EmbeddingModel(
        name="text-embedding-3-small",
        dimensions=1536,
        mteb_avg=62.3,
        cost_per_1m="$0.02",
        latency_p50="12ms",
        notes="Cheapest Azure-native option",
        provider="azure_openai",
    ),
    "text-embedding-3-large": EmbeddingModel(
        name="text-embedding-3-large",
        dimensions=3072,
        mteb_avg=64.6,
        cost_per_1m="$0.13",
        latency_p50="18ms",
        notes="Higher fidelity, still fast",
        provider="azure_openai",
    ),
    "bge-m3": EmbeddingModel(
        name="BGE-M3",
        dimensions=1024,
        mteb_avg=66.1,
        cost_per_1m="Self-hosted",
        latency_p50="25ms",
        notes="Dense + sparse + multi-vector in one pass",
        provider="self_hosted",
    ),
    "cohere-embed-v3": EmbeddingModel(
        name="Cohere embed-v3",
        dimensions=1024,
        mteb_avg=64.5,
        cost_per_1m="$0.10",
        latency_p50="15ms",
        notes="Strong multilingual",
        provider="cohere",
    ),
}


# ── Reranker models ───────────────────────────────────────────────────


class RerankerModel(BaseModel):
    name: str
    notes: str
    provider: str  # azure_native | self_hosted | cohere


RERANKER_MODELS: dict[str, RerankerModel] = {
    "azure-semantic-ranker": RerankerModel(
        name="Azure semantic ranker",
        notes=(
            "Built-in cross-encoder in AI Search. No external deployment. "
            "Enable via SemanticConfiguration."
        ),
        provider="azure_native",
    ),
    "bge-reranker-v2-m3": RerankerModel(
        name="bge-reranker-v2-m3",
        notes="Strong BEIR performance, open weights, single GPU. Default cross-encoder.",
        provider="self_hosted",
    ),
    "rank1": RerankerModel(
        name="Rank1",
        notes="Reasoning-intensive swap-in for complex queries.",
        provider="self_hosted",
    ),
    "cohere-reranker": RerankerModel(
        name="Cohere reranker",
        notes="Hosted reranker API, no self-hosting needed.",
        provider="cohere",
    ),
}
