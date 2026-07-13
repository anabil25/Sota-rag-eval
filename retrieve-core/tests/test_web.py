"""Tests for web/app.py — FastAPI endpoints."""

import os
import tempfile

import pytest
from fastapi.testclient import TestClient

from retrieve.db import RetrieveDB
from retrieve.web.app import create_app


@pytest.fixture
def client():
    """Test client with a temporary config and DB."""
    tmpdir = tempfile.mkdtemp()
    db_path = os.path.join(tmpdir, "test.db")
    config_path = os.path.join(tmpdir, "test.yaml")

    # Write config
    with open(config_path, "w") as f:
        f.write(f"db_path: {db_path}\narchitectures:\n  - hybrid\n  - keyword\n")

    # Seed the DB with test data
    db = RetrieveDB(db_path)
    eid = db.create_eval_set("v1", notes="test")
    q1 = db.add_question(eid, "What form?", "direct_lookup", ["100::0"])
    q2 = db.add_question(eid, "How long?", "process_procedure", ["101::0"])
    db.update_eval_set_counts(eid)

    rid = db.create_run(eid, "hybrid", "test")
    db.add_result(
        rid,
        q1,
        ["100::0"],
        {"recall_at_5": 1.0, "recall_at_10": 1.0, "mrr_at_10": 1.0, "ndcg_at_10": 1.0},
        45.0,
    )
    db.add_result(
        rid,
        q2,
        ["101::0"],
        {"recall_at_5": 1.0, "recall_at_10": 1.0, "mrr_at_10": 1.0, "ndcg_at_10": 0.8},
        50.0,
    )
    db.complete_run(
        rid,
        {
            "recall_at_5": 1.0,
            "recall_at_10": 1.0,
            "mrr_at_10": 1.0,
            "ndcg_at_10": 0.9,
            "avg_latency_ms": 47.5,
            "failure_count": 0,
            "total_questions": 2,
        },
    )
    db.close()

    app = create_app(config_path)
    yield TestClient(app)


class TestFrontendRedirects:
    def test_home(self, client):
        resp = client.get("/", follow_redirects=False)
        assert resp.status_code == 302
        assert resp.headers["location"] == "http://127.0.0.1:5173/"

    def test_compare(self, client):
        resp = client.get("/compare", follow_redirects=False)
        assert resp.status_code == 302
        assert resp.headers["location"] == "http://127.0.0.1:5173/flow/compare"

    def test_history(self, client):
        resp = client.get("/history", follow_redirects=False)
        assert resp.status_code == 302
        assert resp.headers["location"] == "http://127.0.0.1:5173/runs"

    def test_eval_sets(self, client):
        resp = client.get("/eval-sets", follow_redirects=False)
        assert resp.status_code == 302
        assert resp.headers["location"] == "http://127.0.0.1:5173/eval-sets"


class TestAPIEndpoints:
    def test_api_status(self, client):
        resp = client.get("/api/status")
        assert resp.status_code == 200
        data = resp.json()
        assert data["eval_set"]["version_label"] == "v1"
        assert data["run_count"] == 1

    def test_api_runs(self, client):
        resp = client.get("/api/runs")
        assert resp.status_code == 200
        data = resp.json()
        assert len(data) == 1
        assert data[0]["architecture_name"] == "hybrid"

    def test_api_run_detail(self, client):
        resp = client.get("/api/runs/1")
        assert resp.status_code == 200
        data = resp.json()
        assert data["run"]["architecture_name"] == "hybrid"
        assert len(data["results"]) == 2
        assert "categories" in data

    def test_api_run_not_found(self, client):
        resp = client.get("/api/runs/999")
        assert resp.status_code == 404

    def test_api_eval_sets(self, client):
        resp = client.get("/api/eval-sets")
        assert resp.status_code == 200
        data = resp.json()
        assert len(data) == 1
        assert data[0]["version_label"] == "v1"

    def test_api_eval_questions(self, client):
        resp = client.get("/api/eval-sets/1/questions")
        assert resp.status_code == 200
        data = resp.json()
        assert len(data) == 2

    def test_api_architectures(self, client):
        resp = client.get("/api/architectures")
        assert resp.status_code == 200
        data = resp.json()
        assert "hybrid" in data
        assert "keyword" in data
        assert "graphrag" in data

    def test_api_models(self, client):
        resp = client.get("/api/models")
        assert resp.status_code == 200
        data = resp.json()
        assert "embedding" in data
        assert "reranker" in data
        assert "text-embedding-3-small" in data["embedding"]

    def test_api_sota_paths(self, client):
        resp = client.get("/api/sota-paths")
        assert resp.status_code == 200
        data = resp.json()
        assert "government-policy" in data
