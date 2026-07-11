"""SOTA path registry — recommended pipelines per use case.

Each path defines a base architecture with an ordered list of toggleable
components. SOTA Eval Mode runs the eval set against every meaningful
combination of toggles to show the per-component delta.

Retrieve recommends a path based on corpus characteristics observed during
ingestion (doc count, cross-ref density, avg doc length).
"""

from __future__ import annotations

from pydantic import BaseModel


class ComponentToggle(BaseModel):
    """A single component that can be toggled in SOTA eval mode."""

    name: str
    options: list[str]
    default: str
    description: str = ""


class SOTAPath(BaseModel):
    """A recommended SOTA retrieval pipeline for a specific use case."""

    name: str
    description: str
    base_architecture: str  # key into ARCHITECTURES registry
    components: list[ComponentToggle]

    # Heuristic thresholds for corpus-based recommendation
    min_doc_count: int = 0
    max_doc_count: int = 999999
    min_cross_ref_density: float = 0.0
    max_cross_ref_density: float = 999.0
    min_avg_doc_length: float = 0.0


SOTA_PATHS: dict[str, SOTAPath] = {
    "government-policy": SOTAPath(
        name="Government Benefits Policy",
        description=(
            "For government benefits manuals, administrative procedures, and regulatory "
            "documents with dense cross-references between policies. Optimized for "
            "caseworker lookup queries and eligibility determination."
        ),
        base_architecture="hybrid-reranker",
        components=[
            ComponentToggle(
                name="semantic_reranker",
                options=["on", "off"],
                default="on",
                description="Azure AI Search built-in semantic reranker (L2 cross-encoder)",
            ),
            ComponentToggle(
                name="chunking_strategy",
                options=["late_chunking", "fixed_512", "fixed_1024"],
                default="late_chunking",
                description="Late chunking preserves cross-chunk context via full-document pooling",
            ),
            ComponentToggle(
                name="embedding_model",
                options=["text-embedding-3-small", "text-embedding-3-large", "bge-m3"],
                default="text-embedding-3-large",
                description="Embedding model for vector search",
            ),
            ComponentToggle(
                name="chunk_size",
                options=["256", "512", "1024"],
                default="512",
                description="Chunk size in tokens",
            ),
            ComponentToggle(
                name="query_expansion",
                options=["on", "off"],
                default="off",
                description="LLM-assisted query rewriting before search",
            ),
            ComponentToggle(
                name="rrf_weights",
                options=["default", "dense_heavy", "sparse_heavy"],
                default="default",
                description="Reciprocal Rank Fusion weight balance between keyword and vector",
            ),
        ],
        min_cross_ref_density=1.0,
    ),
    "product-docs": SOTAPath(
        name="Product Documentation",
        description=(
            "For product manuals, API docs, and technical documentation. "
            "Mostly standalone pages with clear headings."
        ),
        base_architecture="hybrid-reranker",
        components=[
            ComponentToggle(
                name="semantic_reranker",
                options=["on", "off"],
                default="on",
            ),
            ComponentToggle(
                name="embedding_model",
                options=["text-embedding-3-small", "text-embedding-3-large"],
                default="text-embedding-3-small",
                description="Smaller model is cost-effective for clear, well-structured docs",
            ),
            ComponentToggle(
                name="chunk_size",
                options=["256", "512", "1024"],
                default="512",
            ),
            ComponentToggle(
                name="query_expansion",
                options=["on", "off"],
                default="off",
            ),
        ],
        max_cross_ref_density=1.0,
        min_avg_doc_length=1500.0,
    ),
    "legal-contracts": SOTAPath(
        name="Legal & Contract Corpus",
        description=(
            "For legal documents, contracts, and compliance materials. "
            "Long documents, precise terminology, and heavy cross-referencing."
        ),
        base_architecture="hybrid-reranker",
        components=[
            ComponentToggle(
                name="semantic_reranker",
                options=["on", "off"],
                default="on",
            ),
            ComponentToggle(
                name="chunking_strategy",
                options=["late_chunking", "fixed_512", "fixed_1024"],
                default="late_chunking",
            ),
            ComponentToggle(
                name="embedding_model",
                options=["text-embedding-3-large", "bge-m3"],
                default="text-embedding-3-large",
            ),
            ComponentToggle(
                name="chunk_size",
                options=["512", "1024"],
                default="1024",
                description="Larger chunks preserve legal clause context",
            ),
            ComponentToggle(
                name="query_expansion",
                options=["on", "off"],
                default="on",
                description="Helps bridge formal legal language to natural queries",
            ),
        ],
        min_avg_doc_length=5000.0,
        min_cross_ref_density=2.0,
    ),
    "knowledge-base-faq": SOTAPath(
        name="Knowledge Base / FAQ",
        description=(
            "For FAQs, help center articles, and short-form knowledge bases. "
            "Short, self-contained documents with minimal cross-references."
        ),
        base_architecture="hybrid",
        components=[
            ComponentToggle(
                name="embedding_model",
                options=["text-embedding-3-small", "text-embedding-3-large"],
                default="text-embedding-3-small",
            ),
            ComponentToggle(
                name="chunk_size",
                options=["256", "512"],
                default="256",
                description="Shorter chunks for short documents",
            ),
            ComponentToggle(
                name="rrf_weights",
                options=["default", "dense_heavy"],
                default="default",
            ),
        ],
        max_avg_doc_length=2000.0,
        max_cross_ref_density=0.5,
    ),
}


def recommend_sota_path(
    doc_count: int,
    avg_doc_length: float,
    cross_ref_density: float,
) -> SOTAPath | None:
    """Recommend a SOTA path based on corpus characteristics from ingestion.

    Returns the best-matching path, or None if no path matches.
    """
    best: SOTAPath | None = None
    best_score = -1

    for path in SOTA_PATHS.values():
        if not (path.min_doc_count <= doc_count <= path.max_doc_count):
            continue
        if not (path.min_cross_ref_density <= cross_ref_density <= path.max_cross_ref_density):
            continue
        if avg_doc_length < path.min_avg_doc_length:
            continue

        # Simple scoring: prefer paths with more specific constraints
        score = 0
        if path.min_cross_ref_density > 0:
            score += 1
        if path.max_cross_ref_density < 999:
            score += 1
        if path.min_avg_doc_length > 0:
            score += 1
        if path.max_doc_count < 999999:
            score += 1

        if score > best_score:
            best = path
            best_score = score

    return best


def generate_toggle_combinations(path: SOTAPath) -> list[dict[str, str]]:
    """Generate all meaningful toggle combinations for a SOTA path.

    Returns list of dicts mapping component name → selected option.
    The first entry is always the full default path.
    """
    # Start with all defaults
    defaults = {c.name: c.default for c in path.components}
    combinations = [defaults.copy()]

    # For each component, generate a variant with each non-default option
    for component in path.components:
        for option in component.options:
            if option == component.default:
                continue
            variant = defaults.copy()
            variant[component.name] = option
            combinations.append(variant)

    return combinations
