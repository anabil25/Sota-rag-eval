"""Reconcile asynchronous graph indexing state into SQLite architecture rows."""

from __future__ import annotations

import json
import subprocess
from datetime import UTC, datetime
from typing import Any

import requests
from azure.core.exceptions import ResourceNotFoundError
from azure.storage.blob import BlobServiceClient

from retrieve.db import RetrieveDB
from retrieve.indexing.blob_upload import _build_credential

_TERMINAL_FAILURE_STATES = {"failed", "cancelled", "canceled", "timed_out", "timeout"}
_IN_PROGRESS_STATES = {"queued", "preparing", "running", "started", "indexing"}
_AZURE_SUCCESS_STATES = {"succeeded", "success", "completed"}
_AZURE_FAILURE_STATES = {"failed", "cancelled", "canceled", "timedout", "timed_out"}


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


def _load_job_blob_status(config: dict[str, Any]) -> dict[str, Any] | None:
    storage_account = str(config.get("storage_account") or "").strip()
    container_name = str(config.get("graph_output_container") or "graphrag").strip()
    status_blob = str(config.get("graph_worker_status_blob") or "").strip().strip("/")
    if not storage_account or not container_name or not status_blob:
        raise ValueError(
            "GraphRAG Container Apps Job reconciliation requires storage and status Blob metadata"
        )
    blob_service = BlobServiceClient(
        account_url=f"https://{storage_account}.blob.core.windows.net",
        credential=_build_credential(),
    )
    try:
        payload = (
            blob_service.get_container_client(container_name)
            .download_blob(status_blob)
            .readall()
        )
    except ResourceNotFoundError:
        return None
    status = json.loads(bytes(payload).decode("utf-8"))
    if not isinstance(status, dict):
        raise ValueError("GraphRAG durable job status must be a JSON object")
    return status


def _load_container_job_status(config: dict[str, Any]) -> dict[str, Any]:
    resource_group = str(config.get("resource_group") or "").strip()
    job_name = str(config.get("graph_job_name") or "").strip()
    execution_name = str(config.get("graph_job_execution_name") or "").strip()
    if not resource_group or not job_name or not execution_name:
        raise ValueError(
            "GraphRAG Container Apps Job reconciliation requires resource group, job, and execution names"
        )
    command = [
        "az",
        "containerapp",
        "job",
        "execution",
        "show",
        "--resource-group",
        resource_group,
        "--name",
        job_name,
        "--job-execution-name",
        execution_name,
        "--output",
        "json",
        "--only-show-errors",
    ]
    subscription_id = str(config.get("subscription_id") or "").strip()
    if subscription_id:
        command.extend(["--subscription", subscription_id])
    result = subprocess.run(
        command,
        check=True,
        capture_output=True,
        text=True,
    )
    execution = json.loads(result.stdout)
    if not isinstance(execution, dict):
        raise ValueError("Container Apps Job execution response must be a JSON object")
    execution_state = str(
        (execution.get("properties") or {}).get("status")
        or execution.get("status")
        or ""
    ).strip().lower()
    if not execution_state:
        raise ValueError("Container Apps Job execution did not report a status")

    durable_status = _load_job_blob_status(config)
    if execution_state in _AZURE_FAILURE_STATES:
        status = dict(durable_status or {})
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
        if durable_status is None:
            raise ValueError(
                "Container Apps Job succeeded without a durable GraphRAG status Blob"
            )
        if str(durable_status.get("state") or "").lower() != "succeeded":
            raise ValueError(
                "Container Apps Job completed but durable GraphRAG status is not succeeded"
            )
        return durable_status

    status = dict(durable_status or {})
    status.update(
        {
            "job_id": str(config.get("graph_worker_job_id") or ""),
            "state": "running",
            "message": str(status.get("message") or "Container Apps Job is running"),
        }
    )
    return status


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
