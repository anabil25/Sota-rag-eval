"""Tests for mutation authentication, authorization, and job admission."""

import base64
import json

import pytest
from fastapi.testclient import TestClient

from retrieve.db import RetrieveDB
from retrieve.web.app import create_app


def _principal_header(*, roles: list[str], user_id: str = "user-123") -> str:
    claims = [
        {"typ": "oid", "val": user_id},
        {"typ": "name", "val": "Test Operator"},
        *({"typ": "roles", "val": role} for role in roles),
    ]
    payload = {
        "auth_typ": "aad",
        "user_id": user_id,
        "claims": claims,
    }
    return base64.b64encode(json.dumps(payload).encode("utf-8")).decode("ascii")


def _client(tmp_path, monkeypatch) -> TestClient:
    config_path = tmp_path / "retrieve.yaml"
    config_path.write_text(
        f"db_path: {tmp_path / 'retrieve.db'}\narchitectures: [keyword]\n",
        encoding="utf-8",
    )
    monkeypatch.setenv("RETRIEVE_AUTH_MODE", "easy_auth")
    return TestClient(create_app(str(config_path)))


@pytest.fixture
def local_client(tmp_path, monkeypatch):
    config_path = tmp_path / "retrieve.yaml"
    config_path.write_text(
        f"db_path: {tmp_path / 'retrieve.db'}\narchitectures: [keyword]\n",
        encoding="utf-8",
    )
    monkeypatch.setenv("RETRIEVE_AUTH_MODE", "local")
    monkeypatch.setenv("RETRIEVE_ENVIRONMENT", "development")
    with TestClient(create_app(str(config_path))) as client:
        yield client


def test_easy_auth_requires_authenticated_principal(tmp_path, monkeypatch):
    with _client(tmp_path, monkeypatch) as client:
        response = client.post("/api/ui/session", json={"selected_mode": "test"})

    assert response.status_code == 401
    assert response.json()["detail"] == "Authentication required"


def test_easy_auth_requires_operator_role(tmp_path, monkeypatch):
    headers = {"x-ms-client-principal": _principal_header(roles=["Reader"])}
    with _client(tmp_path, monkeypatch) as client:
        response = client.post(
            "/api/ui/session",
            json={"selected_mode": "test"},
            headers=headers,
        )

    assert response.status_code == 403
    assert "role required" in response.json()["detail"]


def test_easy_auth_operator_can_mutate(tmp_path, monkeypatch):
    headers = {"x-ms-client-principal": _principal_header(roles=["Retrieve.Operator"])}
    with _client(tmp_path, monkeypatch) as client:
        response = client.post(
            "/api/ui/session",
            json={"selected_mode": "test"},
            headers=headers,
        )

    assert response.status_code == 200
    assert response.json()["session"]["selected_mode"] == "test"


def test_production_rejects_local_auth_mode(tmp_path, monkeypatch):
    config_path = tmp_path / "retrieve.yaml"
    config_path.write_text(
        f"db_path: {tmp_path / 'retrieve.db'}\narchitectures: [keyword]\n",
        encoding="utf-8",
    )
    monkeypatch.setenv("RETRIEVE_AUTH_MODE", "local")
    monkeypatch.setenv("RETRIEVE_ENVIRONMENT", "production")
    monkeypatch.delenv("RETRIEVE_ALLOW_INSECURE_LOCAL", raising=False)
    with TestClient(create_app(str(config_path))) as client:
        response = client.post("/api/ui/session", json={"selected_mode": "test"})

    assert response.status_code == 503
    assert "forbidden in production" in response.json()["detail"]


def test_active_job_blocks_direct_mutation(local_client):
    local_client.app.state.jobs["active"] = {
        "id": "active",
        "kind": "index",
        "operation_id": "active",
        "done": False,
        "error": "",
        "result": {},
    }

    response = local_client.post(
        "/api/ui/session",
        json={"selected_mode": "test"},
    )

    assert response.status_code == 409
    assert "already running" in response.json()["detail"]
    local_client.app.state.jobs.clear()


def test_job_idempotency_replays_and_rejects_payload_conflict(
    monkeypatch,
    local_client,
):
    from retrieve.ingest import run as ingest_run

    class _Stats:
        doc_count = 1
        avg_doc_length = 10.0
        cross_ref_density = 0.0

    monkeypatch.setattr(ingest_run, "run_ingest", lambda **kwargs: _Stats())
    headers = {"Idempotency-Key": "ingest-request-001"}
    payload = {
        "kind": "ingest",
        "args": {"source": "source-a", "plugin": "html", "output": "out"},
    }

    first = local_client.post("/api/ui/job/start", json=payload, headers=headers)
    second = local_client.post("/api/ui/job/start", json=payload, headers=headers)
    conflict = local_client.post(
        "/api/ui/job/start",
        json={**payload, "args": {**payload["args"], "source": "source-b"}},
        headers=headers,
    )

    assert first.status_code == 200
    assert second.status_code == 200
    assert second.json()["job_id"] == first.json()["job_id"]
    assert second.json()["idempotent_replay"] is True
    assert conflict.status_code == 409
    assert "reused" in conflict.json()["detail"]


def test_interrupted_job_is_durable_after_backend_restart(tmp_path, monkeypatch):
    db_path = tmp_path / "retrieve.db"
    config_path = tmp_path / "retrieve.yaml"
    config_path.write_text(
        f"db_path: {db_path}\narchitectures: [keyword]\n",
        encoding="utf-8",
    )
    db = RetrieveDB(db_path)
    db.admit_operation_job(
        job_id="interrupted-job",
        kind="provision",
        owner_id="owner-1",
        request_hash="hash-1",
    )
    db.update_operation_job("interrupted-job", state="running")
    db.close()
    monkeypatch.setenv("RETRIEVE_AUTH_MODE", "local")

    with TestClient(create_app(str(config_path))) as client:
        status = client.get("/api/ui/job/interrupted-job/status")

    assert status.status_code == 200
    assert status.json()["state"] == "failed"
    assert status.json()["done"] is True
    assert "restarted" in status.json()["error"]
