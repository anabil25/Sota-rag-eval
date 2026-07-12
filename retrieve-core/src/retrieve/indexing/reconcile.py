"""Reconcile asynchronous graph indexing state into SQLite architecture rows."""

from __future__ import annotations

import json
import subprocess
from datetime import UTC, datetime
from typing import Any

import requests

from retrieve.db import RetrieveDB
from retrieve.graphrag_worker.protocol import parse_job_result
from retrieve.indexing.container_job import (
    container_job_state,
    get_container_job_execution,
    get_container_job_logs,
)

_TERMINAL_FAILURE_STATES = {"failed", "cancelled", "canceled", "timed_out", "timeout"}
_IN_PROGRESS_STATES = {"queued", "preparing", "running", "started", "indexing"}
_AZURE_SUCCESS_STATES = {"succeeded", "success", "completed"}
_AZURE_FAILURE_STATES = {
    "failed",
    "cancelled",
    "canceled",
    "stopped",
    "timedout",
    "timed_out",
}


def _now() -> str:
    return datetime.now(UTC).isoformat()


def _persist_architecture(
    db: RetrieveDB,
    architecture_id: int,
    status: str,
    config: dict[str, Any],
) -> None:
    db.conn.execute(
        "UPDATE architectures SET status = ?, config = ?, resources_provisioned = ? WHERE id = ?",
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


def _load_container_job_result(config: dict[str, Any]) -> dict[str, Any]:
    logs = get_container_job_logs(
        job_name=str(config.get("graph_job_name") or ""),
        execution_name=str(config.get("graph_job_execution_name") or ""),
        resource_group=str(config.get("resource_group") or ""),
        subscription_id=str(config.get("subscription_id") or ""),
    )
    result = parse_job_result(logs)
    if result.get("kind") != "index" or not isinstance(result.get("status"), dict):
        raise ValueError("Container Apps Job logs contain no durable GraphRAG index status")
    return result["status"]


def _load_container_job_status(config: dict[str, Any]) -> dict[str, Any]:
    resource_group = str(config.get("resource_group") or "").strip()
    job_name = str(config.get("graph_job_name") or "").strip()
    execution_name = str(config.get("graph_job_execution_name") or "").strip()
    if not resource_group or not job_name or not execution_name:
        raise ValueError(
            "GraphRAG Container Apps Job reconciliation requires resource group, "
            "job, and execution names"
        )
    subscription_id = str(config.get("subscription_id") or "").strip()
    execution = get_container_job_execution(
        job_name=job_name,
        execution_name=execution_name,
        resource_group=resource_group,
        subscription_id=subscription_id,
    )
    execution_state = container_job_state(execution)
    if not execution_state:
        raise ValueError("Container Apps Job execution did not report a status")

    if execution_state in _AZURE_FAILURE_STATES:
        try:
            status = dict(_load_container_job_result(config))
        except (ValueError, subprocess.CalledProcessError):
            status = {}
        status.update(
            {
                "job_id": str(config.get("graph_worker_job_id") or ""),
                "state": "failed",
                "error": str(
                    (execution.get("properties") or {}).get("statusDetails")
                    or status.get("error")
                    or f"Container Apps Job execution ended as {execution_state}"
                ),
            }
        )
        return status
    if execution_state in _AZURE_SUCCESS_STATES:
        durable_status = _load_container_job_result(config)
        if str(durable_status.get("state") or "").lower() != "succeeded":
            raise ValueError(
                "Container Apps Job completed but durable GraphRAG status is not succeeded"
            )
        return durable_status

    return {
        "job_id": str(config.get("graph_worker_job_id") or ""),
        "state": "running",
        "message": "Container Apps Job is running",
    }


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

    expected_contract = {
        "run_scope": config.get("graph_worker_run_scope")
        or config.get("graphrag_run_scope"),
        "max_documents": (
            config.get("graph_worker_max_documents")
            if config.get("graph_worker_max_documents") is not None
            else config.get("graphrag_max_documents")
        ),
        "chunk_size": config.get("graph_worker_chunk_size"),
        "chunk_overlap": config.get("graph_worker_chunk_overlap"),
    }
    expected_required_document_ids = list(
        config.get("graph_worker_required_document_ids") or []
    )
    for field, value in expected_contract.items():
        target = f"graph_worker_{field}"
        if config.get(target) in (None, "") and value not in (None, ""):
            config[target] = value

    try:
        if config.get("graph_job_execution_name"):
            worker_status = _load_container_job_status(config)
        else:
            status_url = _expected_status_url(config)
            response = requests.get(status_url, timeout=timeout)
            response.raise_for_status()
            worker_status = response.json()
        if not isinstance(worker_status, dict):
            raise ValueError("GraphRAG worker status must be a JSON object")
        if str(worker_status.get("job_id") or "") != str(config["graph_worker_job_id"]):
            raise ValueError("GraphRAG worker status job ID mismatch")

        state = str(worker_status.get("state") or "").lower()
        config["cloud_index_status"] = state
        optional_fields = {
            "message": ("cloud_index_message", lambda value: str(value or "")[:1_000]),
            "error": ("cloud_index_error", lambda value: str(value or "")[:2_000]),
            "updated_at": ("cloud_index_updated_at", lambda value: str(value or "")),
            "heartbeat_at": ("cloud_index_heartbeat_at", lambda value: str(value or "")),
            "current_workflow": (
                "graph_worker_current_workflow",
                lambda value: str(value or ""),
            ),
            "completed_workflows": (
                "graph_worker_completed_workflows",
                lambda value: list(value or []),
            ),
            "progress_description": (
                "graph_worker_progress_description",
                lambda value: str(value or ""),
            ),
            "progress_completed": ("graph_worker_progress_completed", lambda value: value),
            "progress_total": ("graph_worker_progress_total", lambda value: value),
            "run_scope": ("graph_worker_run_scope", lambda value: str(value or "")),
            "max_documents": ("graph_worker_max_documents", lambda value: value),
            "chunk_size": ("graph_worker_chunk_size", lambda value: value),
            "chunk_overlap": ("graph_worker_chunk_overlap", lambda value: value),
            "required_document_ids": (
                "graph_worker_required_document_ids",
                lambda value: list(value or []),
            ),
            "selected_document_ids": (
                "graph_worker_selected_document_ids",
                lambda value: list(value or []),
            ),
            "sample_selection": ("graph_worker_sample_selection", lambda value: str(value or "")),
            "model_metrics": (
                "graph_worker_model_metrics",
                lambda value: dict(value or {}),
            ),
        }
        for source, (target, normalize) in optional_fields.items():
            if source in worker_status:
                config[target] = normalize(worker_status[source])
        config["graph_worker_last_reconciled_at"] = _now()
        if state == "succeeded":
            artifact_prefix = _immutable_artifact_prefix(config, worker_status)
            for field, expected in expected_contract.items():
                if expected in (None, ""):
                    continue
                actual = worker_status.get(field)
                if field != "run_scope":
                    expected = int(expected)
                    actual = int(actual) if actual is not None else None
                if actual != expected:
                    raise ValueError(
                        f"GraphRAG worker {field} does not match the architecture"
                    )
            if expected_required_document_ids:
                selected_document_ids = set(worker_status.get("selected_document_ids") or [])
                missing_required = [
                    document_id
                    for document_id in expected_required_document_ids
                    if document_id not in selected_document_ids
                ]
                if missing_required:
                    raise ValueError(
                        "GraphRAG worker selection omitted required documents: "
                        + ", ".join(missing_required[:5])
                    )
            workflow_results = worker_status.get("workflow_results") or []
            if any(result.get("error") for result in workflow_results if isinstance(result, dict)):
                raise ValueError("GraphRAG worker reported failed workflow results")
            config["graph_worker_artifact_prefix"] = artifact_prefix
            architecture_status = "active"
        elif state in _TERMINAL_FAILURE_STATES:
            architecture_status = "failed"
        elif state in _IN_PROGRESS_STATES:
            architecture_status = "indexing"
        else:
            raise ValueError(f"Unknown GraphRAG worker state: {state or '<empty>'}")
    except (
        requests.RequestException,
        subprocess.CalledProcessError,
        json.JSONDecodeError,
        UnicodeDecodeError,
        ValueError,
    ) as exc:
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
