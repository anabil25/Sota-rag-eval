"""GraphRAG 3.1 settings generation.

Keep this module free of GraphRAG imports so the core package can still be used
without the optional ``graphrag`` extra. Contract tests load the generated
mapping through the pinned upstream package.
"""

from __future__ import annotations

import re
from pathlib import Path
from typing import Any

DEFAULT_CONCURRENT_REQUESTS = 2
DEFAULT_RETRY_MAX_RETRIES = 12
DEFAULT_RETRY_BASE_DELAY_SECONDS = 2.0
DEFAULT_RETRY_MAX_DELAY_SECONDS = 120.0
DEFAULT_EMBEDDING_TPM = 100_000
DEFAULT_EMBEDDING_RPM = 100
DEFAULT_LLM_TPM = 10_000
DEFAULT_LLM_RPM = 10

# Interim safe defaults for FastGraphRAG. A representative benchmark must pick
# the final production value before a full-corpus run is allowed.
DEFAULT_FAST_CHUNK_SIZE = 300
DEFAULT_FAST_CHUNK_OVERLAP = 0
DEFAULT_STANDARD_CHUNK_SIZE = 1_200
DEFAULT_STANDARD_CHUNK_OVERLAP = 100


def _search_index_name(value: str) -> str:
    normalized = re.sub(r"[^a-z0-9-]", "-", value.lower()).strip("-")
    normalized = re.sub(r"-{2,}", "-", normalized)[:128].rstrip("-")
    if len(normalized) < 2:
        raise ValueError(f"Invalid GraphRAG Azure AI Search index name: {value!r}")
    return normalized


def _collect_model_extras(value: Any, path: str = "config") -> list[str]:
    """Return paths of fields accepted only as Pydantic extras."""
    from pydantic import BaseModel

    if isinstance(value, BaseModel):
        extras = [f"{path}.{name}" for name in (value.model_extra or {})]
        for field_name in type(value).model_fields:
            extras.extend(_collect_model_extras(getattr(value, field_name), f"{path}.{field_name}"))
        return extras
    if isinstance(value, dict):
        extras: list[str] = []
        for key, item in value.items():
            extras.extend(_collect_model_extras(item, f"{path}[{key!r}]"))
        return extras
    if isinstance(value, (list, tuple)):
        extras = []
        for index, item in enumerate(value):
            extras.extend(_collect_model_extras(item, f"{path}[{index}]"))
        return extras
    return []


def validate_graphrag_settings(settings: dict[str, Any]) -> Any:
    """Parse settings with GraphRAG 3.1 and reject silently ignored extras."""
    try:
        from graphrag.config.models.graph_rag_config import GraphRagConfig
    except ImportError as exc:  # pragma: no cover - exercised in minimal installs
        raise RuntimeError(
            "graphrag==3.1.0 is required to validate generated GraphRAG settings"
        ) from exc

    config = GraphRagConfig.model_validate(settings)
    extras = _collect_model_extras(config)
    if extras:
        raise ValueError("Unexpected GraphRAG configuration fields: " + ", ".join(sorted(extras)))
    return config


def _retry_config(
    *,
    max_retries: int,
    base_delay_seconds: float,
    max_delay_seconds: float,
) -> dict[str, Any]:
    return {
        "type": "exponential_backoff",
        "max_retries": max_retries,
        "base_delay": base_delay_seconds,
        "jitter": True,
        "max_delay": max_delay_seconds,
    }


def _rate_limit_config(*, requests_per_minute: int, tokens_per_minute: int) -> dict[str, Any]:
    return {
        "type": "sliding_window",
        "period_in_seconds": 60,
        "requests_per_period": requests_per_minute,
        "tokens_per_period": tokens_per_minute,
    }


def build_graphrag_settings(
    *,
    input_dir: str | Path,
    ai_services_endpoint: str,
    llm_model: str = "gpt-4.1",
    embedding_model: str = "text-embedding-3-large",
    method: str = "fast",
    concurrent_requests: int = DEFAULT_CONCURRENT_REQUESTS,
    retry_max_retries: int = DEFAULT_RETRY_MAX_RETRIES,
    retry_base_delay_seconds: float = DEFAULT_RETRY_BASE_DELAY_SECONDS,
    retry_max_delay_seconds: float = DEFAULT_RETRY_MAX_DELAY_SECONDS,
    embedding_tokens_per_minute: int = DEFAULT_EMBEDDING_TPM,
    embedding_requests_per_minute: int = DEFAULT_EMBEDDING_RPM,
    llm_tokens_per_minute: int = DEFAULT_LLM_TPM,
    llm_requests_per_minute: int = DEFAULT_LLM_RPM,
    chunk_size: int | None = None,
    chunk_overlap: int | None = None,
    storage_account_blob_url: str = "",
    storage_container: str = "graphrag",
    run_prefix: str = "",
    cache_prefix: str = "",
    search_endpoint: str = "",
    vector_index_prefix: str = "",
    embedding_dimensions: int = 3_072,
    reporting_dir: str | Path = "logs",
) -> dict[str, Any]:
    """Build a GraphRAG 3.1-compatible configuration mapping.

    The caller remains responsible for serializing the mapping and for choosing
    durable cloud storage. This first implementation batch corrects the model
    contract and FastGraphRAG graph defaults while preserving existing local
    file storage behavior.
    """
    is_fast = method.lower().startswith("fast")
    if chunk_size is None:
        chunk_size = DEFAULT_FAST_CHUNK_SIZE if is_fast else DEFAULT_STANDARD_CHUNK_SIZE
    if chunk_overlap is None:
        chunk_overlap = DEFAULT_FAST_CHUNK_OVERLAP if is_fast else DEFAULT_STANDARD_CHUNK_OVERLAP
    if chunk_size <= 0:
        raise ValueError("GraphRAG chunk size must be positive")
    if chunk_overlap < 0 or chunk_overlap >= chunk_size:
        raise ValueError("GraphRAG chunk overlap must be non-negative and less than chunk size")

    retry = _retry_config(
        max_retries=retry_max_retries,
        base_delay_seconds=retry_base_delay_seconds,
        max_delay_seconds=retry_max_delay_seconds,
    )
    completion_model = {
        "model_provider": "azure",
        "model": llm_model,
        "api_base": ai_services_endpoint,
        "api_version": "2025-04-01-preview",
        "auth_method": "azure_managed_identity",
        "azure_deployment_name": llm_model,
        "retry": dict(retry),
        "rate_limit": _rate_limit_config(
            requests_per_minute=llm_requests_per_minute,
            tokens_per_minute=llm_tokens_per_minute,
        ),
    }
    embedding_model_config = {
        "model_provider": "azure",
        "model": embedding_model,
        "api_base": ai_services_endpoint,
        "api_version": "2025-04-01-preview",
        "auth_method": "azure_managed_identity",
        "azure_deployment_name": embedding_model,
        "retry": dict(retry),
        "rate_limit": _rate_limit_config(
            requests_per_minute=embedding_requests_per_minute,
            tokens_per_minute=embedding_tokens_per_minute,
        ),
    }

    if storage_account_blob_url:
        if not storage_container or not run_prefix or not cache_prefix:
            raise ValueError(
                "Persistent GraphRAG Blob storage requires a container, run prefix, "
                "and cache prefix"
            )
        blob_base = {
            "type": "blob",
            "account_url": storage_account_blob_url,
            "container_name": storage_container,
        }
        output_storage = {**blob_base, "base_dir": f"{run_prefix.strip('/')}/output"}
        update_output_storage = {
            **blob_base,
            "base_dir": f"{run_prefix.strip('/')}/update-output",
        }
        reporting = {
            "type": "file",
            "base_dir": Path(reporting_dir).as_posix(),
        }
        cache = {
            "type": "json",
            "storage": {**blob_base, "base_dir": cache_prefix.strip("/")},
        }
    else:
        output_storage = {"type": "file", "base_dir": "output"}
        update_output_storage = {"type": "file", "base_dir": "update_output"}
        reporting = {"type": "file", "base_dir": "logs"}
        cache = {
            "type": "json",
            "storage": {"type": "file", "base_dir": "cache"},
        }

    if search_endpoint:
        if not vector_index_prefix:
            raise ValueError(
                "Persistent GraphRAG Azure AI Search storage requires vector_index_prefix"
            )
        vector_store = {
            "type": "azure_ai_search",
            "url": search_endpoint,
            "vector_size": embedding_dimensions,
            "index_schema": {
                "entity_description": {
                    "index_name": _search_index_name(f"{vector_index_prefix}-entity"),
                    "vector_size": embedding_dimensions,
                },
                "community_full_content": {
                    "index_name": _search_index_name(f"{vector_index_prefix}-community"),
                    "vector_size": embedding_dimensions,
                },
                "text_unit_text": {
                    "index_name": _search_index_name(f"{vector_index_prefix}-text-unit"),
                    "vector_size": embedding_dimensions,
                },
            },
        }
    else:
        vector_store = {"type": "lancedb", "db_uri": "output/lancedb"}

    return {
        "concurrent_requests": concurrent_requests,
        "completion_models": {"default_completion_model": completion_model},
        "embedding_models": {"default_embedding_model": embedding_model_config},
        "input": {"type": "text", "file_pattern": ".*\\.md"},
        "input_storage": {"type": "file", "base_dir": Path(input_dir).as_posix()},
        "output_storage": output_storage,
        "update_output_storage": update_output_storage,
        "reporting": reporting,
        "cache": cache,
        "vector_store": vector_store,
        "chunking": {
            "type": "tokens",
            "size": chunk_size,
            "overlap": chunk_overlap,
            "encoding_model": "o200k_base",
        },
        "embed_text": {"embedding_model_id": "default_embedding_model"},
        "extract_graph": {
            "completion_model_id": "default_completion_model",
            "entity_types": [
                "organization",
                "person",
                "geo",
                "event",
                "policy",
                "regulation",
            ],
            "max_gleanings": 1,
        },
        "summarize_descriptions": {
            "completion_model_id": "default_completion_model",
            "max_length": 500,
        },
        "extract_graph_nlp": {
            "normalize_edge_weights": True,
            "text_analyzer": {
                "extractor_type": "regex_english",
                "max_word_length": 15,
            },
        },
        "prune_graph": {
            "min_node_freq": 2,
            "min_node_degree": 1,
            "min_edge_weight_pct": 40.0,
        },
        "cluster_graph": {"max_cluster_size": 10},
        "extract_claims": {
            "enabled": False,
            "completion_model_id": "default_completion_model",
            "description": "Claims or facts relevant to information discovery.",
            "max_gleanings": 1,
        },
        "community_reports": {
            "completion_model_id": "default_completion_model",
            "max_length": 2_000,
            "max_input_length": 8_000,
        },
        "snapshots": {"graphml": False, "embeddings": False},
        "local_search": {
            "completion_model_id": "default_completion_model",
            "embedding_model_id": "default_embedding_model",
        },
        "global_search": {
            "completion_model_id": "default_completion_model",
        },
        "drift_search": {
            "completion_model_id": "default_completion_model",
            "embedding_model_id": "default_embedding_model",
        },
        "basic_search": {
            "completion_model_id": "default_completion_model",
            "embedding_model_id": "default_embedding_model",
        },
    }
