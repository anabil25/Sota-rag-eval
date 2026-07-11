"""Cost and artifact-safety gates for GraphRAG indexing."""

from __future__ import annotations

import os
from typing import Literal

GraphRagRunScope = Literal["sample", "canary", "full"]

FULL_RUN_APPROVAL_ENV = "RETRIEVE_GRAPHRAG_FULL_RUN_APPROVED"
SAMPLE_DOCUMENT_LIMIT = 50
CANARY_DOCUMENT_LIMIT = 500
_TRUTHY = {"1", "true", "yes"}


def _full_run_is_approved() -> bool:
    return os.environ.get(FULL_RUN_APPROVAL_ENV, "").strip().lower() in _TRUTHY


def validate_graphrag_run_scope(
    run_scope: GraphRagRunScope,
    max_documents: int | None,
) -> int | None:
    """Validate an indexing scope and return its enforced document cap.

    Full-corpus execution is deliberately default-denied. Sample and canary
    labels are not trusted on their own: each requires a positive hard cap.
    """
    if run_scope == "full":
        if max_documents is not None:
            raise ValueError("A full GraphRAG run cannot set max_documents")
        if not _full_run_is_approved():
            raise RuntimeError(
                "Full-corpus GraphRAG indexing is locked. Complete sample and canary "
                f"validation, then set {FULL_RUN_APPROVAL_ENV}=true for the approved run."
            )
        return None

    if max_documents is None or max_documents <= 0:
        raise ValueError(f"GraphRAG {run_scope} runs require a positive max_documents cap")

    scope_limit = SAMPLE_DOCUMENT_LIMIT if run_scope == "sample" else CANARY_DOCUMENT_LIMIT
    if max_documents > scope_limit:
        raise ValueError(
            f"GraphRAG {run_scope} runs are capped at {scope_limit} documents; "
            f"requested {max_documents}"
        )
    return max_documents


def validate_graphrag_artifact_prefix(output_prefix: str) -> None:
    """Prevent a running job from mutating the promoted current-index alias."""
    normalized = output_prefix.strip().strip("/").lower()
    if normalized == "indexes/current":
        raise ValueError(
            "GraphRAG jobs must write to an immutable run prefix, not indexes/current"
        )
