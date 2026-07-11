"""Tests for durable asynchronous GraphRAG architecture reconciliation."""

import json
from types import SimpleNamespace
from unittest.mock import MagicMock, patch

import requests

from retrieve.db import RetrieveDB
from retrieve.indexing.reconcile import reconcile_graphrag_architecture


def _architecture(db: RetrieveDB, fingerprint: str = "f" * 64) -> dict:
    job_id = "job123"
    endpoint = "https://worker.internal"
    db.register_architecture(
        "graphrag",
        {
            "graph_worker_endpoint": endpoint,
            "graph_worker_job_id": job_id,
            "graph_worker_status_url": f"{endpoint}/index/{job_id}/status",
            "graph_worker_artifact_prefix": f"runs/{fingerprint}/{job_id}",
            "corpus_fingerprint": fingerprint,
            "cloud_index_status": "started",
        },
    )
    db.conn.execute("UPDATE architectures SET status = 'indexing'")
    db.conn.commit()
    architecture = db.get_architecture("graphrag")
    assert architecture is not None
    return architecture


def _response(payload: dict) -> MagicMock:
    response = MagicMock()
    response.json.return_value = payload
    return response


def _job_architecture(db: RetrieveDB, fingerprint: str = "f" * 64) -> dict:
    db.register_architecture(
        "graphrag",
        {
            "resource_group": "rg-test",
            "subscription_id": "sub-test",
            "storage_account": "teststore",
            "graph_output_container": "graphrag",
            "graph_job_name": "azgrjtest",
            "graph_job_execution_name": "azgrjtest-abc",
            "graph_worker_job_id": "job123",
            "graph_worker_status_blob": "jobs/job123/status.json",
            "graph_worker_artifact_prefix": f"runs/{fingerprint}/job123",
            "corpus_fingerprint": fingerprint,
            "cloud_index_status": "started",
            "graph_worker_run_scope": "sample",
        },
    )
    db.conn.execute("UPDATE architectures SET status = 'indexing'")
    db.conn.commit()
    architecture = db.get_architecture("graphrag")
    assert architecture is not None
    return architecture


@patch("retrieve.indexing.reconcile.requests.get")
def test_successful_run_becomes_active(mock_get, tmp_path):
    db = RetrieveDB(tmp_path / "retrieve.db")
    architecture = _architecture(db)
    mock_get.return_value = _response(
        {
            "job_id": "job123",
            "state": "succeeded",
            "message": "Complete",
            "updated_at": "2026-07-10T00:00:00Z",
            "heartbeat_at": "2026-07-10T00:00:00Z",
            "artifact_prefix": f"runs/{'f' * 64}/job123",
            "corpus_fingerprint": "f" * 64,
            "completed_workflows": ["create_final_documents"],
            "workflow_results": [
                {"workflow": "create_final_documents", "error": ""}
            ],
        }
    )

    reconciled = reconcile_graphrag_architecture(db, architecture)

    assert reconciled["status"] == "active"
    assert reconciled["config"]["cloud_index_status"] == "succeeded"
    assert reconciled["config"]["graph_worker_artifact_prefix"] == (
        f"runs/{'f' * 64}/job123"
    )
    assert reconciled["config"]["graph_worker_completed_workflows"] == [
        "create_final_documents"
    ]
    db.close()


@patch("retrieve.indexing.reconcile.requests.get")
def test_terminal_worker_failure_remains_failed(mock_get, tmp_path):
    db = RetrieveDB(tmp_path / "retrieve.db")
    architecture = _architecture(db)
    mock_get.return_value = _response(
        {
            "job_id": "job123",
            "state": "failed",
            "message": "Failed",
            "error": "429 budget exhausted",
        }
    )

    reconciled = reconcile_graphrag_architecture(db, architecture)

    assert reconciled["status"] == "failed"
    assert reconciled["config"]["cloud_index_error"] == "429 budget exhausted"
    db.close()


@patch("retrieve.indexing.reconcile.requests.get")
def test_transient_status_outage_keeps_indexing(mock_get, tmp_path):
    db = RetrieveDB(tmp_path / "retrieve.db")
    architecture = _architecture(db)
    mock_get.side_effect = requests.ConnectionError("temporary DNS failure")

    reconciled = reconcile_graphrag_architecture(db, architecture)

    assert reconciled["status"] == "indexing"
    assert "temporary DNS failure" in reconciled["config"][
        "graph_worker_reconciliation_error"
    ]
    db.close()


@patch("retrieve.indexing.reconcile.requests.get")
def test_tampered_status_url_fails_without_request(mock_get, tmp_path):
    db = RetrieveDB(tmp_path / "retrieve.db")
    architecture = _architecture(db)
    architecture["config"]["graph_worker_status_url"] = "https://attacker.example/status"
    db.conn.execute(
        "UPDATE architectures SET config = ? WHERE id = ?",
        (json.dumps(architecture["config"]), architecture["id"]),
    )
    db.conn.commit()

    reconciled = reconcile_graphrag_architecture(db, architecture)

    assert reconciled["status"] == "failed"
    assert "does not match" in reconciled["config"]["graph_worker_reconciliation_error"]
    mock_get.assert_not_called()
    db.close()


@patch("retrieve.indexing.reconcile._load_job_blob_status")
@patch("retrieve.indexing.reconcile.subprocess.run")
def test_container_job_and_durable_status_must_both_succeed(
    mock_run, mock_blob_status, tmp_path
):
    db = RetrieveDB(tmp_path / "retrieve.db")
    architecture = _job_architecture(db)
    mock_run.return_value = SimpleNamespace(
        stdout=json.dumps({"properties": {"status": "Succeeded"}})
    )
    mock_blob_status.return_value = {
        "job_id": "job123",
        "state": "succeeded",
        "artifact_prefix": f"runs/{'f' * 64}/job123",
        "corpus_fingerprint": "f" * 64,
        "run_scope": "sample",
        "workflow_results": [],
    }

    reconciled = reconcile_graphrag_architecture(db, architecture)

    assert reconciled["status"] == "active"
    assert reconciled["config"]["cloud_index_status"] == "succeeded"
    command = mock_run.call_args.args[0]
    assert command[:5] == ["az", "containerapp", "job", "execution", "show"]
    assert "azgrjtest-abc" in command
    db.close()


@patch("retrieve.indexing.reconcile._load_job_blob_status")
@patch("retrieve.indexing.reconcile.subprocess.run")
def test_hard_failed_container_job_overrides_stale_running_blob(
    mock_run, mock_blob_status, tmp_path
):
    db = RetrieveDB(tmp_path / "retrieve.db")
    architecture = _job_architecture(db)
    mock_run.return_value = SimpleNamespace(
        stdout=json.dumps(
            {
                "properties": {
                    "status": "Failed",
                    "statusDetails": "Replica timeout",
                }
            }
        )
    )
    mock_blob_status.return_value = {
        "job_id": "job123",
        "state": "running",
        "artifact_prefix": f"runs/{'f' * 64}/job123",
    }

    reconciled = reconcile_graphrag_architecture(db, architecture)

    assert reconciled["status"] == "failed"
    assert reconciled["config"]["cloud_index_error"] == "Replica timeout"
    db.close()
