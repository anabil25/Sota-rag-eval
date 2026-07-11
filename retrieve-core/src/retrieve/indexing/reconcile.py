"""Reconcile asynchronous graph indexing state into SQLite architecture rows."""

from __future__ import annotations

import json
from datetime import UTC, datetime
from typing import Any

import requests

from retrieve.db import RetrieveDB

_TERMINAL_FAILURE_STATES = {"failed", "cancelled", "canceled", "timed_out", "timeout"}
_IN_PROGRESS_STATES = {"queued", "preparing", "running", "started", "indexing"}


def _now() -> str:
    return datetime.now(UTC).isoformat()


def _persist_architecture(
    db: RetrieveDB,
    architecture_id: int,
    status: str,
    config: dict[str, Any],
) -> None:
    db.conn.execute(
        "UPDATE architectures SET status = ?, config = ?, resources_provisioned = ? "
        "WHERE id = ?",
        (status, json.dumps(config), json.dumps(config), architecture_id),
    )
    db.conn.commit()


def _expected_status_url(config: dict[str, Any]) -> str:
    endpoint = str(config.get("graph_worker_endpoint") or "").strip().rstrip("/")
    job_id = str(config.get("graph_worker_job_id") or "").strip()
    if not endpoint or not job_id:
        raise ValueError("GraphRAG reconciliation requires a worker endpoint and job ID")
    expected = f"{endpoint}/index/{job_id}/status"
    stored = str(config.get("graph_worker_status_url") or "").strip()
    if stored and stored != expected:
        raise ValueError("Stored GraphRAG status URL does not match its worker endpoint/job ID")
    return expected


def _immutable_artifact_prefix(config: dict[str, Any], status: dict[str, Any]) -> str:
    fingerprint = str(config.get("corpus_fingerprint") or "").strip()
    job_id = str(config.get("graph_worker_job_id") or "").strip()
    expected = f"runs/{fingerprint}/{job_id}"
    actual = str(status.get("artifact_prefix") or "").strip().strip("/")
    if len(fingerprint) != 64 or actual != expected:
        raise ValueError("GraphRAG worker returned an invalid immutable artifact prefix")
    status_fingerprint = str(status.get("corpus_fingerprint") or fingerprint)
    if status_fingerprint != fingerprint:
        raise ValueError("GraphRAG worker corpus fingerprint does not match the architecture")
    return actual


def reconcile_graphrag_architecture(
    db: RetrieveDB,
    architecture: dict[str, Any],
    *,
    timeout: tuple[float, float] = (3.0, 10.0),
) -> dict[str, Any]:
    """Poll one GraphRAG job and persist an evidence-based architecture state."""
    if architecture.get("name") != "graphrag":
        return architecture
    architecture_id = int(architecture["id"])
    config = dict(architecture.get("config") or {})
    if not config.get("graph_worker_job_id"):
        return architecture

    try:
        status_url = _expected_status_url(config)
        response = requests.get(status_url, timeout=timeout)
        response.raise_for_status()
        worker_status = response.json()
        if not isinstance(worker_status, dict):
            raise ValueError("GraphRAG worker status must be a JSON object")
        if str(worker_status.get("job_id") or "") != str(config["graph_worker_job_id"]):
            raise ValueError("GraphRAG worker status job ID mismatch")

        state = str(worker_status.get("state") or "").lower()
        config.update(
            {
                "cloud_index_status": state,
                "cloud_index_message": str(worker_status.get("message") or "")[:1_000],
                "cloud_index_error": str(worker_status.get("error") or "")[:2_000],
                "cloud_index_updated_at": str(worker_status.get("updated_at") or ""),
                "cloud_index_heartbeat_at": str(worker_status.get("heartbeat_at") or ""),
                "graph_worker_current_workflow": str(
                    worker_status.get("current_workflow") or ""
                ),
                "graph_worker_completed_workflows": list(
                    worker_status.get("completed_workflows") or []
                ),
                "graph_worker_progress_description": str(
                    worker_status.get("progress_description") or ""
                ),
                "graph_worker_progress_completed": worker_status.get(
                    "progress_completed"
                ),
                "graph_worker_progress_total": worker_status.get("progress_total"),
                "graph_worker_run_scope": str(worker_status.get("run_scope") or ""),
                "graph_worker_max_documents": worker_status.get("max_documents"),
                "graph_worker_last_reconciled_at": _now(),
            }
        )
        if state == "succeeded":
            artifact_prefix = _immutable_artifact_prefix(config, worker_status)
            expected_scope = str(config.get("graph_worker_run_scope") or "")
            if expected_scope and worker_status.get("run_scope") != expected_scope:
                raise ValueError("GraphRAG worker run scope does not match the architecture")
            workflow_results = worker_status.get("workflow_results") or []
            if any(
                result.get("error")
                for result in workflow_results
                if isinstance(result, dict)
            ):
                raise ValueError("GraphRAG worker reported failed workflow results")
            config["graph_worker_artifact_prefix"] = artifact_prefix
            architecture_status = "active"
        elif state in _TERMINAL_FAILURE_STATES:
            architecture_status = "failed"
        elif state in _IN_PROGRESS_STATES:
            architecture_status = "indexing"
        else:
            raise ValueError(f"Unknown GraphRAG worker state: {state or '<empty>'}")
    except (requests.RequestException, ValueError) as exc:
        config["graph_worker_reconciliation_error"] = str(exc)[:2_000]
        config["graph_worker_last_reconciled_at"] = _now()
        architecture_status = str(architecture.get("status") or "indexing")
        if isinstance(exc, ValueError):
            architecture_status = "failed"

    _persist_architecture(db, architecture_id, architecture_status, config)
    return db.get_architecture("graphrag") or architecture


def reconcile_architecture_rows(
    db: RetrieveDB,
    architectures: list[dict[str, Any]],
) -> list[dict[str, Any]]:
    """Reconcile supported asynchronous architectures before returning status."""
    reconciled = []
    for architecture in architectures:
        config = architecture.get("config") or {}
        needs_graph_reconcile = (
            architecture.get("name") == "graphrag"
            and config.get("graph_worker_job_id")
            and (
                architecture.get("status") == "indexing"
                or config.get("cloud_index_status") in _IN_PROGRESS_STATES
            )
        )
        if needs_graph_reconcile:
            architecture = reconcile_graphrag_architecture(db, architecture)
        reconciled.append(architecture)
    return reconciled
