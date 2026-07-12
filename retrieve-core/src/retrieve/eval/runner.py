"""Evaluation runner — queries search endpoints, computes metrics, classifies misses.

Retrieval queries go directly to Azure AI Search REST API.
Copilot SDK is used ONLY for miss classification on queries with zero recall.
"""

from __future__ import annotations

import asyncio
import concurrent.futures
import json
import logging
import time
import uuid
from typing import Any

from azure.identity import DefaultAzureCredential
from azure.search.documents import SearchClient
from azure.search.documents.models import VectorizableTextQuery
from rich.console import Console
from rich.progress import Progress

from retrieve.config import RetrieveConfig
from retrieve.copilot import get_client, run_sync, stop_client
from retrieve.db import RetrieveDB
from retrieve.eval.metrics import aggregate_scores, compute_scores
from retrieve.ingest.manifest import build_document_id_aliases, load_corpus_manifest
from retrieve.observability import emit_error, emit_progress, step

log = logging.getLogger(__name__)
console = Console()

_client_cache: dict[tuple[str, str], SearchClient] = {}

_SEARCH_RUNTIME_OPTIONS = {
    "query_syntax",
    "lexical_search_mode",
    "search_fields",
    "filter_expression",
    "scoring_profile",
    "top_k",
}
_VECTOR_RUNTIME_OPTIONS = {
    "vector_k",
    "vector_filter_mode",
    "vector_weight",
    "vector_exhaustive",
}
_SEMANTIC_RUNTIME_OPTIONS = {
    "semantic_ranker_mode",
    "semantic_captions",
    "semantic_answers",
    "query_rewrites",
    "semantic_max_wait_ms",
}
_RUNTIME_QUERY_OPTIONS: dict[str, set[str]] = {
    "keyword": _SEARCH_RUNTIME_OPTIONS,
    "single-vector": _VECTOR_RUNTIME_OPTIONS | {"top_k", "filter_expression"},
    "hybrid": _SEARCH_RUNTIME_OPTIONS | _VECTOR_RUNTIME_OPTIONS,
    "hybrid-reranker": (
        _SEARCH_RUNTIME_OPTIONS | _VECTOR_RUNTIME_OPTIONS | _SEMANTIC_RUNTIME_OPTIONS
    ),
    "hybrid-llm-enriched": (
        _SEARCH_RUNTIME_OPTIONS | _VECTOR_RUNTIME_OPTIONS | _SEMANTIC_RUNTIME_OPTIONS
    ),
    "agentic-kb": {
        "top_k",
        "agentic_reasoning_effort",
        "agentic_output_mode",
        "agentic_max_runtime_seconds",
        "agentic_include_activity",
    },
    "graphrag": {"graphrag_query_mode"},
    "lightrag": {
        "lightrag_query_mode",
        "lightrag_top_k",
        "lightrag_chunk_top_k",
        "lightrag_enable_rerank",
        "lightrag_response_type",
        "lightrag_debug_mode",
    },
}

# ── Cost estimation data (from service-matrix.md) ─────────────────────
# Per-hour eval cost and estimated monthly production cost by architecture.
COST_ESTIMATES: dict[str, dict[str, float]] = {
    "keyword": {"per_hour": 0.10, "monthly": 70.0, "dominant": "AI Search Basic"},
    "single-vector": {"per_hour": 0.30, "monthly": 180.0, "dominant": "AI Search + embedding TPM"},
    "hybrid": {"per_hour": 0.30, "monthly": 190.0, "dominant": "AI Search + embedding TPM"},
    "hybrid-reranker": {
        "per_hour": 0.40,
        "monthly": 280.0,
        "dominant": "AI Search + embedding TPM + semantic",
    },
    "hybrid-llm-enriched": {
        "per_hour": 0.50,
        "monthly": 300.0,
        "dominant": "AI Search + embedding + LLM (index-time)",
    },
    "multi-vector": {
        "per_hour": 0.80,
        "monthly": 320.0,
        "dominant": "Foundry managed compute + AI Search",
    },
    "agentic-kb": {
        "per_hour": 0.60,
        "monthly": 350.0,
        "dominant": "AI Search KB + LLM (query planning)",
    },
    "graphrag": {
        "per_hour": 3.00,
        "monthly": 850.0,
        "dominant": "Indexing + Blob + AI Search + Container Apps",
    },
    "lightrag": {"per_hour": 0.80, "monthly": 350.0, "dominant": "Container Apps + LLM calls"},
}


def estimate_cost(
    arch_name: str,
    query_count: int,
    queries_per_month: int = 10000,
) -> dict[str, Any]:
    """Estimate eval run cost and projected monthly production cost.

    Args:
        arch_name: Base architecture name.
        query_count: Number of queries in the eval run.
        queries_per_month: Assumed monthly query volume for production estimate.

    Returns:
        Dict with eval_run_cost, monthly_estimate, per_query_cost, dominant_cost.
    """
    base = arch_name.split("+")[0].strip() if "+" in arch_name else arch_name
    # Look up cost data, fall back to hybrid as a reasonable default
    cost_data = COST_ESTIMATES.get(base, COST_ESTIMATES.get("hybrid", {}))
    per_hour = cost_data.get("per_hour", 0.30)
    monthly_base = cost_data.get("monthly", 190.0)
    dominant = cost_data.get("dominant", "Unknown")

    # Assume ~1200 queries/hour at 0.3s throttle
    queries_per_hour = 3600 / 0.3 if base != "keyword" else 3600 / 0.05
    eval_hours = query_count / queries_per_hour
    eval_run_cost = eval_hours * per_hour

    # Monthly estimate scales base cost by query volume factor
    volume_factor = queries_per_month / 10000
    monthly_estimate = monthly_base * volume_factor

    return {
        "eval_run_cost": round(eval_run_cost, 4),
        "monthly_estimate": round(monthly_estimate, 2),
        "per_query_cost": round(per_hour / queries_per_hour, 6),
        "dominant_cost": dominant,
        "architecture": arch_name,
        "query_count": query_count,
        "queries_per_month": queries_per_month,
    }


def _get_search_client(endpoint: str, index_name: str) -> SearchClient:
    """Return a cached SearchClient for the given endpoint + index.

    Avoids re-acquiring Azure tokens and re-creating HTTP connections on
    every query call during an eval run.
    """
    key = (endpoint, index_name)
    if key not in _client_cache:
        _client_cache[key] = SearchClient(endpoint, index_name, DefaultAzureCredential())
    return _client_cache[key]


def _extract_doc_id(identifier: str) -> str:
    """Extract the source document identifier from various ID formats.

    Generalizable to any corpus — not tied to policy numbering conventions.

    Handles:
    - "100-10_ethical_conduct::0" → "100-10_ethical_conduct"  (chunk ID from eval gen)
    - "100-10_ethical_conduct.md" → "100-10_ethical_conduct"   (filename from search)
    - "aGVsbG8="                  → "aGVsbG8="                 (base64 ID, passthrough)
    """
    s = identifier.strip().replace("\\", "/")
    # Strip chunk index suffix before checking the extension.
    if "::" in s:
        s = s.split("::", 1)[0]
    for ext in (".md", ".htm", ".html", ".txt", ".pdf"):
        if s.endswith(ext):
            s = s[: -len(ext)]
            break
    return s


def _canonical_doc_id(identifier: str, aliases: dict[str, str]) -> str:
    normalized = _extract_doc_id(identifier)
    return aliases.get(normalized, aliases.get(identifier, normalized))


def _retrieval_questions(questions: list[dict[str, Any]]) -> list[dict[str, Any]]:
    """Return active questions that have evidence for retrieval scoring."""
    return [
        question
        for question in questions
        if str(question.get("status") or "active").lower() == "active"
        and bool(question.get("ground_truth_chunk_ids"))
    ]


def _config_bool(value: Any, *, default: bool) -> bool:
    if isinstance(value, bool):
        return value
    if value in (None, ""):
        return default
    return str(value).strip().lower() in {"1", "true", "yes", "on"}


def build_query_runtime_kwargs(arch_config: dict[str, Any]) -> dict[str, Any]:
    """Build the supported query-time contract from persisted architecture config."""
    return {
        "top_k": int(arch_config.get("top_k", 10)),
        "query_syntax": arch_config.get("query_syntax", "simple"),
        "lexical_search_mode": arch_config.get("lexical_search_mode", "any"),
        "search_fields": arch_config.get("search_fields", ""),
        "filter_expression": arch_config.get("filter_expression", ""),
        "scoring_profile": arch_config.get("scoring_profile", ""),
        "vector_k": arch_config.get("vector_k", 50),
        "vector_filter_mode": arch_config.get("vector_filter_mode", "preFilter"),
        "vector_weight": arch_config.get("vector_weight", 1),
        "vector_exhaustive": arch_config.get("vector_exhaustive", False),
        "semantic_ranker_mode": arch_config.get("semantic_ranker_mode", "auto"),
        "semantic_max_wait_ms": arch_config.get("semantic_max_wait_ms", 1000),
        "agentic_reasoning_effort": arch_config.get("agentic_reasoning_effort", "low"),
        "agentic_output_mode": arch_config.get("agentic_output_mode", "extractiveData"),
        "agentic_max_runtime_seconds": arch_config.get("agentic_max_runtime_seconds", 30),
        "agentic_include_activity": arch_config.get("agentic_include_activity", True),
        "graphrag_mode": arch_config.get("graphrag_query_mode", "local"),
        "ai_services_endpoint": arch_config.get("ai_services_endpoint", ""),
        "function_endpoint": arch_config.get("function_endpoint", ""),
        "graph_worker_endpoint": arch_config.get("graph_worker_endpoint", ""),
        "graph_job_name": arch_config.get("graph_job_name", ""),
        "resource_group": arch_config.get("resource_group", ""),
        "subscription_id": arch_config.get("subscription_id", ""),
        "graph_worker_artifact_prefix": arch_config.get("graph_worker_artifact_prefix", ""),
        "corpus_fingerprint": arch_config.get("corpus_fingerprint", ""),
        "storage_account": arch_config.get("storage_account", ""),
        "graph_output_container": arch_config.get("graph_output_container", "graphrag"),
        "lightrag_mode": arch_config.get("lightrag_query_mode", "mix"),
        "lightrag_working_dir": arch_config.get("lightrag_working_dir", ".lightrag"),
        "container_app_endpoint": arch_config.get("container_app_endpoint", ""),
        "embedding_model": arch_config.get("embedding_model", "text-embedding-3-large"),
        "llm_model": arch_config.get("llm_model", "gpt-4.1"),
        "lightrag_top_k": arch_config.get("lightrag_top_k", 40),
        "lightrag_chunk_top_k": arch_config.get("lightrag_chunk_top_k", 20),
        "lightrag_enable_rerank": arch_config.get("lightrag_enable_rerank", True),
        "lightrag_response_type": arch_config.get(
            "lightrag_response_type", "Multiple Paragraphs"
        ),
        "lightrag_debug_mode": arch_config.get("lightrag_debug_mode", "none"),
    }


_DERIVED_MODEL_METRICS = {
    "failure_rate",
    "retry_rate",
    "compute_duration_per_response_seconds",
    "cache_hit_rate",
    "tokens_per_response",
    "cost_per_response",
}


def aggregate_model_metrics(
    samples: list[dict[str, dict[str, int | float]]],
) -> dict[str, dict[str, int | float]]:
    """Aggregate raw model counters and recompute derived rates."""
    from graphrag_llm.metrics.metrics_aggregator import metrics_aggregator

    aggregated: dict[str, dict[str, int | float]] = {}
    for sample in samples:
        for model_id, metrics in sample.items():
            totals = aggregated.setdefault(model_id, {})
            for name, value in metrics.items():
                if name not in _DERIVED_MODEL_METRICS and isinstance(value, (int, float)):
                    totals[name] = totals.get(name, 0) + value

    for metrics in aggregated.values():
        metrics_aggregator.aggregate(metrics)
    return aggregated


# ── Search query adapters ─────────────────────────────────────────────
# Each architecture uses its native query mode per azure-ai-search.md skill:
#   keyword        → search_text only (BM25)
#   single-vector  → vector_queries only (ANN via vectorizer)
#   hybrid         → search_text + vector_queries (RRF fusion)
#   hybrid-reranker→ search_text + vector_queries + semantic reranker


def query_ai_search(
    endpoint: str,
    index_name: str,
    query: str,
    arch_name: str = "keyword",
    top_k: int = 10,
    toggles: dict[str, Any] | None = None,
    **kwargs,
) -> tuple[list[str], float]:
    """Query Azure AI Search using the architecture's native query mode.

    Uses DefaultAzureCredential — requires Search Index Data Reader role.
    Dispatches query type based on arch_name per azure-ai-search.md skill patterns.
    Client and credential are cached per (endpoint, index_name) to avoid
    token re-acquisition overhead across queries in an eval run.

        `toggles` carries SOTA-mode runtime overrides. The only currently
        executable override is semantic_reranker: "on"|"off".
    """
    client = _get_search_client(endpoint, index_name)
    toggles = toggles or {}
    unsupported_toggles = sorted(set(toggles) - {"semantic_reranker"})
    if unsupported_toggles:
        raise ValueError(
            "Unsupported SOTA toggle(s) require distinct implemented query/index paths: "
            + ", ".join(unsupported_toggles)
        )

    vector_query = VectorizableTextQuery(
        text=query,
        k=int(kwargs.get("vector_k", 50)),
        fields="content_vector",
        weight=float(kwargs.get("vector_weight", 1)),
        exhaustive=_config_bool(kwargs.get("vector_exhaustive"), default=False),
    )

    # Only retrieve fields needed for ID extraction — avoids pulling large content blobs
    search_kwargs: dict[str, Any] = {
        "top": top_k,
        "select": ["id", "doc_id", "metadata_storage_name"],
    }
    search_fields = [
        field.strip() for field in str(kwargs.get("search_fields", "")).split(",") if field.strip()
    ]
    if search_fields:
        search_kwargs["search_fields"] = search_fields
    for key, value in (
        ("filter", kwargs.get("filter_expression")),
        ("scoring_profile", kwargs.get("scoring_profile")),
        ("vector_filter_mode", kwargs.get("vector_filter_mode")),
    ):
        if value:
            search_kwargs[key] = value
    lexical_mode = str(kwargs.get("lexical_search_mode") or "").strip()
    if lexical_mode in {"all", "any"}:
        search_kwargs["search_mode"] = lexical_mode
    query_syntax = str(kwargs.get("query_syntax") or "").strip()
    if query_syntax in {"simple", "full"}:
        search_kwargs["query_type"] = query_syntax

    if arch_name == "keyword":
        # Keyword only — BM25
        search_kwargs["search_text"] = query

    elif arch_name == "single-vector":
        # Pure vector — ANN via index vectorizer, no keyword
        search_kwargs["search_text"] = None
        search_kwargs["vector_queries"] = [vector_query]

    elif arch_name == "hybrid":
        # Hybrid — keyword + vector (RRF fusion)
        # scoring_statistics="global" normalises BM25 scores across shards
        # for more consistent RRF fusion weights
        search_kwargs["search_text"] = query
        search_kwargs["scoring_statistics"] = "global"
        search_kwargs["vector_queries"] = [vector_query]

    elif arch_name in ("hybrid-reranker", "hybrid-llm-enriched"):
        # Hybrid + semantic reranker
        search_kwargs["search_text"] = query
        search_kwargs["scoring_statistics"] = "global"
        search_kwargs["vector_queries"] = [vector_query]
        # SOTA toggle: semantic_reranker can be turned off at query time to
        # measure the marginal value of L2 reranking on the same index.
        semantic_default = str(kwargs.get("semantic_ranker_mode", "auto")) != "off"
        if toggles.get("semantic_reranker", "on" if semantic_default else "off") != "off":
            search_kwargs["query_type"] = "semantic"
            search_kwargs["semantic_configuration_name"] = "default-semantic"
            semantic_wait = kwargs.get("semantic_max_wait_ms")
            if semantic_wait not in (None, ""):
                search_kwargs["semantic_max_wait_in_milliseconds"] = int(semantic_wait)

    elif arch_name == "multi-vector":
        # Multi-vector — same as hybrid-reranker, possibly with AML vectorizer
        search_kwargs["search_text"] = query
        search_kwargs["scoring_statistics"] = "global"
        search_kwargs["vector_queries"] = [vector_query]
        search_kwargs["query_type"] = "semantic"
        search_kwargs["semantic_configuration_name"] = "default-semantic"

    elif arch_name == "agentic-kb":
        # Agentic Knowledge Base — delegates to KnowledgeBaseRetrievalClient
        from retrieve.indexing.advanced import query_agentic_kb

        return query_agentic_kb(
            endpoint=endpoint,
            kb_name=index_name,
            query=query,
            top_k=top_k,
            reasoning_effort=kwargs.get("agentic_reasoning_effort", "low"),
            output_mode=kwargs.get("agentic_output_mode", "extractiveData"),
            max_runtime_seconds=int(kwargs.get("agentic_max_runtime_seconds", 30)),
            include_activity=_config_bool(
                kwargs.get("agentic_include_activity"), default=True
            ),
        )

    elif arch_name == "graphrag":
        # GraphRAG — delegates to the configured remote endpoint or local graphrag
        from retrieve.indexing.advanced import query_graphrag

        return query_graphrag(
            query=query,
            mode=kwargs.get("graphrag_mode", "local"),
            corpus_dir=kwargs.get("corpus_dir", "corpus"),
            ai_services_endpoint=kwargs.get("ai_services_endpoint", ""),
            function_endpoint=kwargs.get("function_endpoint", ""),
            graph_worker_endpoint=kwargs.get("graph_worker_endpoint", ""),
            graph_job_name=kwargs.get("graph_job_name", ""),
            resource_group=kwargs.get("resource_group", ""),
            subscription_id=kwargs.get("subscription_id", ""),
            artifact_prefix=kwargs.get("graph_worker_artifact_prefix", ""),
            corpus_fingerprint=kwargs.get("corpus_fingerprint", ""),
            storage_account=kwargs.get("storage_account", ""),
            output_container=kwargs.get("graph_output_container", "graphrag"),
            search_endpoint=endpoint,
            metrics_sink=kwargs.get("graphrag_metrics_sink"),
        )

    elif arch_name == "lightrag":
        # LightRAG — delegates to Container Apps endpoint or local lightrag
        from retrieve.indexing.advanced import query_lightrag

        return query_lightrag(
            query=query,
            mode=kwargs.get("lightrag_mode", "mix"),
            working_dir=kwargs.get("lightrag_working_dir", ".lightrag"),
            ai_services_endpoint=kwargs.get("ai_services_endpoint", ""),
            container_app_endpoint=kwargs.get("container_app_endpoint", ""),
            corpus_dir=kwargs.get("corpus_dir", "corpus"),
            embedding_model=kwargs.get("embedding_model", "text-embedding-3-large"),
            llm_model=kwargs.get("llm_model", "gpt-4.1"),
            top_k=int(kwargs.get("lightrag_top_k", 40)),
            chunk_top_k=int(kwargs.get("lightrag_chunk_top_k", 20)),
            enable_rerank=_config_bool(
                kwargs.get("lightrag_enable_rerank"), default=True
            ),
            response_type=kwargs.get("lightrag_response_type", "Multiple Paragraphs"),
            debug_mode=kwargs.get("lightrag_debug_mode", "none"),
        )

    else:
        # Fallback — keyword search for unknown architectures
        search_kwargs["search_text"] = query

    max_retries = 5
    for attempt in range(max_retries + 1):
        start = time.perf_counter()
        try:
            results = client.search(**search_kwargs)
            chunk_ids = []
            for r in results:
                # Prefer doc_id (filename stem, generalizable) → metadata_storage_name → id
                cid = r.get("doc_id") or r.get("metadata_storage_name") or r.get("id", "")
                if cid:
                    chunk_ids.append(str(cid))
            latency_ms = (time.perf_counter() - start) * 1000
            return chunk_ids, latency_ms
        except Exception as e:
            latency_ms = (time.perf_counter() - start) * 1000
            err_str = str(e)
            # DNS resolution failure means the search service doesn't exist — fail fast
            if "Failed to resolve" in err_str or "getaddrinfo failed" in err_str:
                raise ConnectionError(
                    f"Search service not reachable for '{arch_name}': {e}\n"
                    "The search service may not have been provisioned. "
                    "Run 'retrieve provision' first."
                ) from e
            # Retry on 429 (embedding vectorizer rate limit) with exponential backoff
            if "429" in err_str or "TooManyRequests" in err_str:
                if attempt < max_retries:
                    wait = 2**attempt  # 1, 2, 4, 8, 16 seconds
                    log.info(
                        "Vectorizer rate-limited for %s, retrying in %ds (attempt %d/%d)",
                        arch_name,
                        wait,
                        attempt + 1,
                        max_retries,
                    )
                    time.sleep(wait)
                    continue
            log.warning("Search query failed for %s: %s", arch_name, e)
            return [], latency_ms
    return [], 0.0


# ── Miss classification via Copilot SDK ───────────────────────────────

MISS_CLASSIFICATION_PROMPT = """You are a retrieval quality analyst.
A search query missed its expected result (recall@10 = 0).

Classify the miss into ONE of these types:
- vocabulary_mismatch: the query uses different terms than the document
- semantic_gap: the query's meaning is related but the embedding/search couldn't bridge it
- cross_ref_miss: the answer requires connecting information across multiple documents
- chunking_boundary: the answer was split across chunk boundaries

Given:
- Question: {question}
- Expected chunk: {expected_chunk}
- Top retrieved chunk (wrong): {wrong_chunk}

Return ONLY a JSON object:
{{"miss_type": "one of the four types", "explanation": "brief explanation"}}
"""


async def _classify_misses(
    misses: list[dict[str, Any]],
    cfg: RetrieveConfig,
) -> list[dict[str, Any]]:
    """Use Copilot SDK to classify why each query missed."""
    from copilot import PermissionHandler

    if not misses:
        return []

    client = await get_client(cfg.copilot)
    session_config: dict[str, Any] = {
        "model": cfg.copilot.model,
        "on_permission_request": PermissionHandler.approve_all,
        "system_message": {"content": "You are a retrieval quality classification expert."},
    }
    if cfg.copilot.provider:
        session_config["provider"] = cfg.copilot.provider.to_sdk_dict()

    classified: list[dict[str, Any]] = []

    async with await client.create_session(**session_config) as session:
        total = len(misses)
        for idx, m in enumerate(misses, start=1):
            prompt = MISS_CLASSIFICATION_PROMPT.format(
                question=m["question"],
                expected_chunk=m.get("expected_chunk", "N/A")[:1000],
                wrong_chunk=m.get("wrong_chunk", "N/A")[:1000],
            )

            emit_progress(
                "Starting miss classification",
                stage="eval_run.classify_misses",
                completed=idx - 1,
                total=total,
            )

            task = asyncio.create_task(session.send_and_wait(prompt, timeout=cfg.copilot.timeout))
            started = time.monotonic()
            while True:
                try:
                    response = await asyncio.wait_for(asyncio.shield(task), timeout=10)
                    break
                except TimeoutError:
                    elapsed = int(time.monotonic() - started)
                    console.print(
                        f"  [dim]Classifying miss {idx}/{total}: waiting on Copilot SDK "
                        f"({elapsed}s)...[/dim]"
                    )
                    emit_progress(
                        "Waiting on Copilot SDK",
                        stage="eval_run.classify_misses",
                        completed=idx - 1,
                        total=total,
                        heartbeat_seconds=elapsed,
                    )

            if response and response.data and response.data.content:
                raw = response.data.content
                try:
                    # Extract JSON
                    if "```json" in raw:
                        start = raw.index("```json") + 7
                        end = raw.index("```", start)
                        raw = raw[start:end]
                    elif "```" in raw:
                        start = raw.index("```") + 3
                        end = raw.index("```", start)
                        raw = raw[start:end]

                    data = json.loads(raw.strip())
                    m["failure_type"] = data.get("miss_type", data.get("failure_type", "unknown"))
                    m["failure_details"] = data.get("explanation", "")
                except (json.JSONDecodeError, ValueError):
                    m["failure_type"] = "unknown"
                    m["failure_details"] = raw[:200]
            else:
                m["failure_type"] = "unknown"
                m["failure_details"] = "No response from Copilot SDK"

            classified.append(m)
            emit_progress(
                "Miss classification complete",
                stage="eval_run.classify_misses",
                completed=idx,
                total=total,
                failure_type=m.get("failure_type", "unknown"),
            )

    return classified


# ── Main evaluation runner ────────────────────────────────────────────


def run_evaluation(
    eval_set_version: str = "latest",
    architectures: list[str] | None = None,
    cfg: RetrieveConfig | None = None,
    variants: list[dict[str, Any]] | None = None,
    mode: str = "test",
    parallel: bool = False,
    experiment_id: str | None = None,
):
    """Run the golden eval set against provisioned search architectures.

    `variants` is a list of dicts ``{"base": <arch_name>, "name": <variant_label>,
    "toggles": {...}}``. When provided, each variant produces its own run record
    so SOTA Eval Mode can compare component on/off configurations head-to-head.
    When ``variants`` is None we fall back to one run per ``architectures`` entry
    with empty toggles (Test Mode behaviour).

    When ``parallel`` is True, variants targeting different base architectures
    (i.e. different search indexes) run concurrently via ThreadPoolExecutor.
    Variants sharing the same base still run serially to avoid vectorizer rate limits.
    """
    if cfg is None:
        cfg = RetrieveConfig()

    db = RetrieveDB(cfg.db_path)
    preexisting_running_ids: set[int] = set()
    try:
        # Get eval set
        with step("eval_run.load_eval_set", eval_set_version=eval_set_version):
            if eval_set_version == "latest":
                eval_set = db.get_latest_eval_set()
            else:
                eval_set = db.get_eval_set_by_version(eval_set_version)

        if not eval_set:
            console.print("[red]No eval set found. Run 'retrieve eval generate' first.[/red]")
            return

        eval_set_id = eval_set["id"]
        experiment_id = experiment_id or uuid.uuid4().hex
        try:
            current_corpus_fingerprint = str(
                load_corpus_manifest(cfg.corpus.output_dir)["corpus_fingerprint"]
            )
        except (FileNotFoundError, ValueError):
            current_corpus_fingerprint = str(cfg.azure.corpus_fingerprint or "")
        preexisting_running_ids = {
            int(row["id"])
            for row in db.conn.execute(
                "SELECT id FROM runs WHERE eval_set_id = ? AND status = 'running'",
                (eval_set_id,),
            ).fetchall()
        }
        with step("eval_run.load_questions", eval_set_id=eval_set_id):
            all_questions = db.get_questions(eval_set_id)
            questions = _retrieval_questions(all_questions)
        skipped_questions = len(all_questions) - len(questions)
        console.print(
            f"\n[bold]Running eval set '{eval_set['version_label']}' "
            f"({len(questions)} retrieval questions)[/bold]\n"
        )
        if skipped_questions:
            console.print(
                f"[dim]Skipped {skipped_questions} inactive or evidence-free question(s) "
                "from retrieval scoring.[/dim]\n"
            )

        if not questions:
            console.print("[red]Eval set has no active questions with retrieval evidence.[/red]")
            return

        # Determine which architectures to eval
        arch_names = architectures or cfg.architectures
        if not arch_names and not variants:
            console.print(
                "[red]No architectures specified. Set in retrieve.yaml or use "
                "--architectures.[/red]"
            )
            return

        # Build the list of (base_arch, variant_label, toggles) tuples to run.
        # Test Mode: one entry per architecture, no toggles, label == base_arch.
        # SOTA Mode: caller passes variants explicitly.
        variants_to_run: list[dict[str, Any]] = []
        if variants:
            for v in variants:
                variants_to_run.append(
                    {
                        "base": v["base"],
                        "name": v.get("name") or v["base"],
                        "toggles": v.get("toggles") or {},
                    }
                )
        else:
            for an in arch_names:
                variants_to_run.append({"base": an, "name": an, "toggles": {}})

        if parallel and len(variants_to_run) > 1:
            # Group by base architecture — variants sharing a base run serially
            # (same index → same vectorizer → rate limits), different bases in parallel.
            from collections import defaultdict

            groups: dict[str, list[dict[str, Any]]] = defaultdict(list)
            for v in variants_to_run:
                groups[v["base"]].append(v)

            console.print(
                f"\n[bold]Running {len(variants_to_run)} variants across "
                f"{len(groups)} base architectures in parallel[/bold]"
            )

            def _run_group(group_variants: list[dict[str, Any]]) -> list[int]:
                # Each thread gets its own DB connection for thread safety
                thread_db = RetrieveDB(cfg.db_path)
                try:
                    return [
                        _eval_variant(
                            v,
                            questions,
                            eval_set_id,
                            str(eval_set["version_label"]),
                            experiment_id,
                            current_corpus_fingerprint,
                            cfg,
                            mode,
                            thread_db,
                        )
                        for v in group_variants
                    ]
                finally:
                    thread_db.close()

            run_ids: list[int] = []
            with concurrent.futures.ThreadPoolExecutor(max_workers=min(len(groups), 4)) as executor:
                futures = [executor.submit(_run_group, g) for g in groups.values()]
                for f in concurrent.futures.as_completed(futures):
                    run_ids.extend(f.result())
        else:
            run_ids = []
            for variant in variants_to_run:
                run_ids.append(
                    _eval_variant(
                        variant,
                        questions,
                        eval_set_id,
                        str(eval_set["version_label"]),
                        experiment_id,
                        current_corpus_fingerprint,
                        cfg,
                        mode,
                        db,
                    )
                )
        experiment = {
            "experiment_id": experiment_id,
            "eval_set_id": int(eval_set_id),
            "eval_set_version": str(eval_set["version_label"]),
            "corpus_fingerprint": current_corpus_fingerprint,
            "architecture_names": sorted({str(v["base"]) for v in variants_to_run}),
            "run_ids": sorted(run_ids),
        }
        session = db.get_generation_preferences("ui_session") or {}
        session.update(
            {
                "active_experiment_id": experiment_id,
                "active_experiment_eval_set_id": int(eval_set_id),
                "active_experiment_eval_set_version": str(eval_set["version_label"]),
                "active_experiment_corpus_fingerprint": current_corpus_fingerprint,
                "active_experiment_architectures": experiment["architecture_names"],
                "run_done": True,
                "compare_done": False,
                "teardown_done": False,
                "winners": [],
            }
        )
        db.upsert_generation_preferences(session, "ui_session")
        return experiment
    except Exception as exc:
        if "eval_set_id" in locals():
            running_rows = db.conn.execute(
                "SELECT id FROM runs WHERE eval_set_id = ? AND status = 'running'",
                (eval_set_id,),
            ).fetchall()
            for row in running_rows:
                run_id = int(row["id"])
                if run_id not in preexisting_running_ids:
                    db.fail_run(run_id)
        emit_error("Evaluation failed", exc, stage="eval_run.failed")
        raise
    finally:
        db.close()


def _eval_variant(
    variant: dict[str, Any],
    questions: list[dict[str, Any]],
    eval_set_id: int,
    eval_set_version: str,
    experiment_id: str,
    corpus_fingerprint: str,
    cfg: RetrieveConfig,
    mode: str,
    db: RetrieveDB,
) -> int:
    """Evaluate a single architecture variant — extracted for parallel support."""
    arch_name = variant["base"]
    variant_label = variant["name"]
    toggles = variant["toggles"]

    console.print(
        f"\n[bold cyan]Evaluating: {variant_label}[/bold cyan]"
        + (f" [dim]({arch_name} + toggles)[/dim]" if toggles else "")
    )
    emit_progress(
        "Starting architecture evaluation",
        stage="eval_run.query",
        architecture=variant_label,
        completed=0,
        total=len(questions),
    )

    # Look up architecture config from DB (or use defaults)
    arch_record = db.get_architecture(arch_name)
    arch_config = dict(arch_record["config"]) if arch_record else {}
    arch_id = arch_record["id"] if arch_record else None
    ui = db.get_generation_preferences("ui_session") or {}
    architecture_options = ui.get("architecture_options") or {}
    selected_options = architecture_options.get(arch_name) or {}
    allowed_options = _RUNTIME_QUERY_OPTIONS.get(arch_name, set())
    if isinstance(selected_options, dict):
        arch_config.update(
            {key: value for key, value in selected_options.items() if key in allowed_options}
        )

    try:
        corpus_manifest = load_corpus_manifest(cfg.corpus.output_dir)
        document_aliases = build_document_id_aliases(corpus_manifest)
    except (FileNotFoundError, ValueError):
        document_aliases = {}

    # Bake toggles into the persisted config so the audit trail captures them
    if toggles:
        arch_config = {**arch_config, **toggles, "_variant_of": arch_name}
    arch_config.update(
        {
            "experiment_id": experiment_id,
            "eval_set_id": eval_set_id,
            "eval_set_version": eval_set_version,
            "candidate_base": arch_name,
        }
    )
    if corpus_fingerprint:
        arch_config["corpus_fingerprint"] = corpus_fingerprint

    # Get search endpoint from config
    search_endpoint = arch_config.get(
        "search_endpoint",
        f"https://{cfg.azure.name_prefix}-search.search.windows.net",
    )
    index_name = arch_config.get("index_name", f"{cfg.azure.name_prefix}-{arch_name}")

    # Create run record (use variant_label so distinct variants don't collide)
    run_id = db.create_run(
        eval_set_id=eval_set_id,
        architecture_name=variant_label,
        mode=mode,
        architecture_config=arch_config,
        architecture_id=arch_id,
    )

    all_scores: list[dict[str, float]] = []
    all_latencies: list[float] = []
    model_metric_samples: list[dict[str, dict[str, int | float]]] = []
    misses_to_classify: list[dict[str, Any]] = []

    # Throttle for architectures that use the embedding vectorizer to avoid 429s.
    # Keyword-only doesn't call the embedding endpoint, so no throttle needed.
    needs_throttle = arch_name != "keyword"

    with Progress() as progress:
        task = progress.add_task(f"Querying {arch_name}...", total=len(questions))

        for qi, q in enumerate(questions):
            # Small delay between vector queries to stay under TPM limit
            if needs_throttle and qi > 0:
                time.sleep(0.3)

            # Query using architecture's native query mode
            query_model_metrics: dict[str, dict[str, int | float]] = {}
            retrieved_ids, latency_ms = query_ai_search(
                endpoint=search_endpoint,
                index_name=index_name,
                query=q["question_text"],
                arch_name=arch_name,
                toggles=toggles,
                corpus_dir=cfg.corpus.output_dir,
                graphrag_metrics_sink=query_model_metrics.update,
                **build_query_runtime_kwargs(arch_config),
            )
            if query_model_metrics:
                model_metric_samples.append(query_model_metrics)

            # Compute metrics — normalize IDs for matching
            ground_truth = q["ground_truth_chunk_ids"]
            ground_truth_doc_ids = {_canonical_doc_id(gt, document_aliases) for gt in ground_truth}
            seen: set[str] = set()
            retrieved_doc_ids: list[str] = []
            for rid in retrieved_ids:
                did = _canonical_doc_id(rid, document_aliases)
                if did not in seen:
                    seen.add(did)
                    retrieved_doc_ids.append(did)
            scores = compute_scores(retrieved_doc_ids, list(ground_truth_doc_ids))
            all_scores.append(scores)
            all_latencies.append(latency_ms)

            emit_progress(
                "Query evaluated",
                stage="eval_run.query",
                architecture=arch_name,
                completed=progress.tasks[0].completed + 1,
                total=len(questions),
                question_id=q["id"],
                recall_at_10=scores["recall_at_10"],
            )

            # Check for miss (none of the ground truth in top 10)
            if scores["recall_at_10"] == 0 and ground_truth:
                misses_to_classify.append(
                    {
                        "question_id": q["id"],
                        "question": q["question_text"],
                        "expected_chunk": ", ".join(ground_truth),
                        "wrong_chunk": retrieved_ids[0] if retrieved_ids else "no results",
                    }
                )

            # Store result
            db.add_result(
                run_id=run_id,
                question_id=q["id"],
                retrieved_chunk_ids=retrieved_ids,
                scores=scores,
                latency_ms=latency_ms,
            )

            progress.advance(task)

    # Classify misses via Copilot SDK
    if misses_to_classify:
        console.print(
            f"\n  [yellow]Classifying {len(misses_to_classify)} misses via Copilot SDK...[/yellow]"
        )

        async def _classify():
            try:
                return await _classify_misses(misses_to_classify, cfg)
            finally:
                await stop_client()

        classified = run_sync(_classify())
        emit_progress(
            "Miss classification batch complete",
            stage="eval_run.classify_misses",
            architecture=arch_name,
            classified=len(classified),
        )

        # Update miss types in DB
        for f in classified:
            results = db.get_results_for_run(run_id)
            for r in results:
                if r["question_id"] == f["question_id"]:
                    db.conn.execute(
                        "UPDATE run_results SET failure_type = ?, failure_details = ? WHERE id = ?",
                        (f.get("failure_type"), f.get("failure_details"), r["id"]),
                    )
        db.conn.commit()

    # Compute aggregates
    agg = aggregate_scores(all_scores)
    agg["avg_latency_ms"] = sum(all_latencies) / len(all_latencies) if all_latencies else 0
    agg["p95_latency_ms"] = (
        sorted(all_latencies)[int(len(all_latencies) * 0.95)] if all_latencies else 0
    )
    agg["miss_count"] = len(misses_to_classify)
    agg["total_questions"] = len(questions)
    if model_metric_samples:
        agg["model_metrics"] = aggregate_model_metrics(model_metric_samples)

    # Cost estimation
    cost = estimate_cost(arch_name, len(questions))
    agg["cost_estimate"] = cost

    db.complete_run(run_id, agg)

    # Print results
    console.print(f"\n  [bold green]Results for {arch_name}:[/bold green]")
    console.print(f"    Recall@5:    [cyan]{agg['recall_at_5']:.3f}[/cyan]")
    console.print(f"    Recall@10:   [cyan]{agg['recall_at_10']:.3f}[/cyan]")
    console.print(f"    MRR@10:      [cyan]{agg['mrr_at_10']:.3f}[/cyan]")
    console.print(f"    nDCG@10:     [cyan]{agg['ndcg_at_10']:.3f}[/cyan]")
    console.print(f"    Avg latency: [cyan]{agg['avg_latency_ms']:.0f}ms[/cyan]")
    console.print(f"    Misses:      [yellow]{agg['miss_count']}/{agg['total_questions']}[/yellow]")
    console.print(f"    Est. cost:   [green]${cost['eval_run_cost']:.4f}[/green] (this run)")
    console.print(
        f"    Monthly est: [green]${cost['monthly_estimate']:.2f}/mo[/green] @ 10k queries"
    )

    # Per-category breakdown
    cat_scores = db.get_per_category_scores(run_id)
    if cat_scores:
        console.print("\n  [bold]Per-category nDCG@10:[/bold]")
        for cat, scores in sorted(cat_scores.items()):
            console.print(f"    {cat}: [cyan]{scores.get('ndcg_at_10', 0):.3f}[/cyan]")

    emit_progress(
        "Architecture evaluation complete",
        stage="eval_run.query",
        architecture=arch_name,
        completed=len(questions),
        total=len(questions),
        recall_at_10=agg["recall_at_10"],
        mrr_at_10=agg["mrr_at_10"],
        ndcg_at_10=agg["ndcg_at_10"],
    )
    return run_id
