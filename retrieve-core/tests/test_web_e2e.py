"""End-to-end test for the rewritten web UI layer.

Verifies that every API endpoint works through FastAPI's TestClient,
confirming that the web layer is a correct thin wrapper over CLI-tested core.
Uses an isolated temp DB and mocks external services (Copilot SDK, Azure Search).
"""

from __future__ import annotations

import json
import time
import tempfile
from pathlib import Path
from typing import Any
from unittest.mock import MagicMock, patch

import pytest
from fastapi.testclient import TestClient

from retrieve.config import RetrieveConfig
from retrieve.db import RetrieveDB
from retrieve.ingest.plugin import CorpusStats


@pytest.fixture()
def tmp_config(tmp_path: Path) -> RetrieveConfig:
    db_path = str(tmp_path / "test.db")
    corpus_dir = tmp_path / "corpus"
    corpus_dir.mkdir()
    # Create a minimal corpus file so generate can find something
    (corpus_dir / "test_doc.md").write_text(
        "---\npolicy_id: \"test-1\"\ntitle: \"Test Doc\"\nparent: \"Root\"\n---\n\n"
        "# Test Doc\n\nThis is test content for evaluation generation.\n",
        encoding="utf-8",
    )
    return RetrieveConfig(
        db_path=db_path,
        corpus={"source": "http://example.com", "plugin": "html", "output_dir": str(corpus_dir)},
        azure={"resource_group": "rg-test", "location": "southcentralus", "name_prefix": "test"},
        architectures=["keyword"],
    )


@pytest.fixture()
def client(tmp_config: RetrieveConfig, tmp_path: Path) -> TestClient:
    # Write a config file
    import yaml
    config_path = tmp_path / "retrieve.yaml"
    config_path.write_text(yaml.dump(tmp_config.model_dump()), encoding="utf-8")

    from retrieve.web.app import create_app
    app = create_app(str(config_path))
    return TestClient(app)


def test_apply_ui_selections_uses_explicit_architectures(tmp_config: RetrieveConfig):
    from retrieve.web.app import _apply_ui_selections

    _apply_ui_selections(
        {"architectures": ["hybrid-reranker", "agentic-kb", "graphrag", "lightrag"]},
        tmp_config,
    )

    assert tmp_config.architectures == [
        "hybrid-reranker",
        "agentic-kb",
        "graphrag",
        "lightrag",
    ]


def test_apply_ui_selections_parses_explicit_architecture_string(tmp_config: RetrieveConfig):
    from retrieve.web.app import _apply_ui_selections

    _apply_ui_selections({"architectures": "keyword, hybrid"}, tmp_config)

    assert tmp_config.architectures == ["keyword", "hybrid"]


@pytest.fixture()
def seeded_db(tmp_config: RetrieveConfig) -> RetrieveDB:
    """Create a DB with an eval set + questions for endpoints that need them."""
    db = RetrieveDB(tmp_config.db_path)
    es_id = db.create_eval_set("v-test", notes="test eval set")
    db.add_question(
        eval_set_id=es_id,
        question_text="What is the confidentiality policy?",
        category="direct_lookup",
        ground_truth_chunk_ids=["test-1::0"],
        source_doc_id="test-1",
    )
    db.add_question(
        eval_set_id=es_id,
        question_text="How do you process a fair hearing?",
        category="process_procedure",
        ground_truth_chunk_ids=["test-1::1"],
        source_doc_id="test-1",
    )
    db.update_eval_set_counts(es_id)

    # Register an architecture
    arch_id = db.register_architecture("keyword", config={
        "search_endpoint": "https://test-search.search.windows.net",
        "index_name": "test-keyword",
    })

    # Create a completed run with results
    run_id = db.create_run(
        eval_set_id=es_id,
        architecture_name="keyword",
        mode="test",
        architecture_config={},
        architecture_id=arch_id,
    )
    db.add_result(
        run_id=run_id,
        question_id=1,
        retrieved_chunk_ids=["test-1"],
        scores={"recall_at_5": 1.0, "recall_at_10": 1.0, "mrr_at_10": 1.0, "ndcg_at_10": 1.0},
        latency_ms=42.0,
    )
    db.add_result(
        run_id=run_id,
        question_id=2,
        retrieved_chunk_ids=["wrong-doc"],
        scores={"recall_at_5": 0.0, "recall_at_10": 0.0, "mrr_at_10": 0.0, "ndcg_at_10": 0.0},
        latency_ms=55.0,
        failure_type="vocabulary_mismatch",
        failure_details="Different terms used",
    )
    db.complete_run(run_id, {
        "recall_at_5": 0.5, "recall_at_10": 0.5,
        "mrr_at_10": 0.5, "ndcg_at_10": 0.5,
        "avg_latency_ms": 48.5, "miss_count": 1, "total_questions": 2,
    })
    db.close()
    return RetrieveDB(tmp_config.db_path)


# ── HTML page tests ───────────────────────────────────────────────────


class TestHTMLPages:
    def test_home_redirects(self, client: TestClient):
        r = client.get("/", follow_redirects=False)
        assert r.status_code == 302
        assert r.headers["location"] == "/step/ingest"

    def test_legacy_redirects(self, client: TestClient):
        for path in ["/compare", "/history", "/eval-sets", "/eval-workbench"]:
            r = client.get(path, follow_redirects=False)
            assert r.status_code == 302

    @pytest.mark.parametrize("step_name", [
        "ingest", "eval", "mode", "configure", "provision", "compare", "history", "settings",
    ])
    def test_step_pages_render(self, client: TestClient, seeded_db: RetrieveDB, step_name: str):
        r = client.get(f"/step/{step_name}")
        assert r.status_code == 200
        assert "text/html" in r.headers["content-type"]

    def test_step_htmx_partial(self, client: TestClient, seeded_db: RetrieveDB):
        r = client.get("/step/ingest", headers={"HX-Request": "true"})
        assert r.status_code == 200

    def test_unknown_step_404(self, client: TestClient):
        r = client.get("/step/nonexistent")
        assert r.status_code == 404


# ── Read-only API tests ───────────────────────────────────────────────


class TestReadAPI:
    def test_status(self, client: TestClient, seeded_db: RetrieveDB):
        r = client.get("/api/status")
        assert r.status_code == 200
        data = r.json()
        assert "eval_set" in data
        assert data["run_count"] == 1

    def test_runs(self, client: TestClient, seeded_db: RetrieveDB):
        r = client.get("/api/runs")
        assert r.status_code == 200
        runs = r.json()
        assert len(runs) == 1
        assert runs[0]["architecture_name"] == "keyword"

    def test_run_detail(self, client: TestClient, seeded_db: RetrieveDB):
        r = client.get("/api/runs/1")
        assert r.status_code == 200
        data = r.json()
        assert len(data["results"]) == 2
        assert len(data["failures"]) == 1
        assert data["failures"][0]["failure_type"] == "vocabulary_mismatch"

    def test_run_not_found(self, client: TestClient):
        r = client.get("/api/runs/999")
        assert r.status_code == 404

    def test_eval_sets(self, client: TestClient, seeded_db: RetrieveDB):
        r = client.get("/api/eval-sets")
        assert r.status_code == 200
        assert len(r.json()) == 1

    def test_eval_questions(self, client: TestClient, seeded_db: RetrieveDB):
        r = client.get("/api/eval-sets/1/questions")
        assert r.status_code == 200
        assert len(r.json()) == 2

    def test_eval_questions_browse(self, client: TestClient, seeded_db: RetrieveDB):
        r = client.get("/api/eval-sets/1/questions/browse?category=direct_lookup")
        assert r.status_code == 200
        data = r.json()
        assert data["total"] == 1
        assert len(data["items"]) == 1

    def test_eval_set_summary(self, client: TestClient, seeded_db: RetrieveDB):
        r = client.get("/api/eval-sets/1/summary")
        assert r.status_code == 200
        data = r.json()
        assert "categories" in data
        assert "examples" in data

    def test_eval_set_summary_not_found(self, client: TestClient):
        r = client.get("/api/eval-sets/999/summary")
        assert r.status_code == 404

    def test_architectures(self, client: TestClient):
        r = client.get("/api/architectures")
        assert r.status_code == 200
        assert isinstance(r.json(), dict)

    def test_models(self, client: TestClient):
        r = client.get("/api/models")
        assert r.status_code == 200
        data = r.json()
        assert "embedding" in data
        assert "reranker" in data

    def test_sota_paths(self, client: TestClient):
        r = client.get("/api/sota-paths")
        assert r.status_code == 200


# ── Preferences / session tests ───────────────────────────────────────


class TestPreferences:
    def test_get_default_preferences(self, client: TestClient):
        r = client.get("/api/eval/preferences")
        assert r.status_code == 200
        assert isinstance(r.json(), dict)

    def test_update_preferences(self, client: TestClient):
        r = client.post("/api/eval/preferences", json={
            "scope_key": "test",
            "preferences": {"coverage_target": 0.9},
        })
        assert r.status_code == 200
        assert r.json()["preferences"]["coverage_target"] == 0.9

        # Read back
        r2 = client.get("/api/eval/preferences?scope_key=test")
        assert r2.json()["coverage_target"] == 0.9

    def test_ui_session_roundtrip(self, client: TestClient):
        r = client.post("/api/ui/session", json={"selected_mode": "test", "ingest_done": True})
        assert r.status_code == 200

        r2 = client.get("/api/ui/session")
        data = r2.json()
        assert data["selected_mode"] == "test"
        assert data["ingest_done"] is True

    def test_ui_session_rejects_non_dict(self, client: TestClient):
        r = client.post("/api/ui/session", json="bad")
        assert r.status_code == 400


# ── Mutation API tests (mocked core) ──────────────────────────────────


class TestMutationAPIs:
    def test_ingest(self, client: TestClient):
        mock_stats = CorpusStats(doc_count=5, avg_doc_length=1200.0, cross_ref_density=2.5)
        with patch("retrieve.ingest.run_ingest", return_value=mock_stats) as mock:
            r = client.post("/api/ingest", json={
                "source": "http://example.com",
                "plugin": "html",
                "output": "corpus",
            })
        assert r.status_code == 200
        data = r.json()
        assert data["status"] == "complete"
        assert data["stats"]["doc_count"] == 5
        mock.assert_called_once()

    def test_eval_generate(self, client: TestClient):
        with patch("retrieve.eval.generate.generate_eval_set", return_value=42):
            r = client.post("/api/eval/generate", json={
                "corpus": "corpus",
                "version": "v-test",
                "mode": "sample",
            })
        assert r.status_code == 200
        assert r.json()["eval_set_id"] == 42

    @pytest.mark.skip(reason="eval_curate API route commented out — deferred until curation UI is built")
    def test_eval_curate(self, client: TestClient, seeded_db: RetrieveDB):
        with patch("retrieve.eval.curate.regenerate_eval_set", return_value=99):
            r = client.post("/api/eval/curate", json={
                "source_version": "v-test",
                "new_version": "v-test-curated",
                "steering": {"more": ["cross_document"]},
            })
        assert r.status_code == 200
        assert r.json()["eval_set_id"] == 99

    def test_export_csv(self, client: TestClient, seeded_db: RetrieveDB, tmp_path: Path):
        output = str(tmp_path / "export.csv")
        with patch("retrieve.eval.io_csv.export_eval_set_to_csv", return_value=2):
            r = client.post("/api/eval/export-csv", json={
                "eval_set": "v-test",
                "output": output,
            })
        assert r.status_code == 200
        assert r.json()["rows"] == 2

    def test_import_csv(self, client: TestClient, seeded_db: RetrieveDB, tmp_path: Path):
        csv_file = tmp_path / "import.csv"
        csv_file.write_text("dummy", encoding="utf-8")
        with patch("retrieve.eval.io_csv.import_eval_set_from_csv", return_value=(10, 5)):
            r = client.post("/api/eval/import-csv", json={
                "input": str(csv_file),
                "version": "v-imported",
            })
        assert r.status_code == 200
        assert r.json()["imported"] == 5

    def test_import_csv_missing_input(self, client: TestClient):
        r = client.post("/api/eval/import-csv", json={"version": "v-bad"})
        assert r.status_code == 400


# ── Job system tests ──────────────────────────────────────────────────


class TestJobSystem:
    def test_start_and_poll_job(self, client: TestClient):
        """Start a job and verify the job system works end-to-end.

        Note: TestClient runs a sync event loop, so asyncio.create_task() may
        not schedule the background task between requests. We test _run_job_sync
        directly to verify the job execution path, and test the HTTP API shape
        separately.
        """
        # Test 1: HTTP API shape — job starts and returns an operation_id
        mock_stats = CorpusStats(doc_count=3, avg_doc_length=800.0, cross_ref_density=1.0)
        with patch("retrieve.ingest.run_ingest", return_value=mock_stats):
            r = client.post("/api/ui/job/start", json={
                "kind": "ingest",
                "args": {"source": "http://example.com"},
            })
        assert r.status_code == 200
        data = r.json()
        assert "job_id" in data
        assert data["kind"] == "ingest"
        assert data["operation_id"] == data["job_id"]

    def test_run_job_sync_directly(self, tmp_config: RetrieveConfig):
        """Test _run_job_sync directly — this is what the async task calls."""
        from retrieve.web.app import _run_job_sync

        mock_stats = CorpusStats(doc_count=3, avg_doc_length=800.0, cross_ref_density=1.0)
        with patch("retrieve.ingest.run_ingest", return_value=mock_stats):
            result = _run_job_sync("ingest", {"source": "http://example.com"}, tmp_config, "test-op-1")

        assert result["doc_count"] == 3

    def test_run_job_sync_error(self, tmp_config: RetrieveConfig):
        """Test _run_job_sync error propagation."""
        from retrieve.web.app import _run_job_sync

        with patch("retrieve.ingest.run_ingest", side_effect=RuntimeError("boom")):
            with pytest.raises(RuntimeError, match="boom"):
                _run_job_sync("ingest", {}, tmp_config, "test-op-2")

    def test_run_job_sync_unknown_kind(self, tmp_config: RetrieveConfig):
        from retrieve.web.app import _run_job_sync

        with pytest.raises(ValueError, match="Unknown job kind"):
            _run_job_sync("nonexistent", {}, tmp_config, "test-op-3")

    def test_job_error_handling(self, client: TestClient):
        """Verify the job start endpoint works even when the job will fail."""
        with patch("retrieve.ingest.run_ingest", side_effect=RuntimeError("boom")):
            r = client.post("/api/ui/job/start", json={
                "kind": "ingest",
                "args": {},
            })
        assert r.status_code == 200
        job_id = r.json()["job_id"]

        # Verify we can poll status (even if task hasn't run yet due to TestClient)
        status = client.get(f"/api/ui/job/{job_id}/status").json()
        assert status["kind"] == "ingest"

    def test_job_not_found(self, client: TestClient):
        r = client.get("/api/ui/job/nonexistent/status")
        assert r.status_code == 404

    def test_sse_stream_not_found(self, client: TestClient):
        r = client.get("/api/ui/job/nonexistent/stream")
        assert r.status_code == 404


# ── Event bus integration test ────────────────────────────────────────


class TestEventBus:
    def test_events_flow_through_bus(self):
        """Verify that emit_progress inside an operation() delivers events to subscribers."""
        import asyncio
        from retrieve.observability import EventBus, operation, emit_progress

        bus = EventBus()
        events_received = []

        async def _test():
            loop = asyncio.get_running_loop()
            op_id = "test-op-123"

            # Subscribe before operation starts
            q = bus.subscribe(op_id, loop)

            # Temporarily patch the global bus
            import retrieve.observability as obs
            original_bus = obs._bus
            obs._bus = bus

            try:
                def _worker():
                    with operation("test.op", source="test", operation_id=op_id):
                        emit_progress("step 1", stage="test")
                        emit_progress("step 2", stage="test")

                await asyncio.to_thread(_worker)

                # Drain queue
                while True:
                    event = await asyncio.wait_for(q.get(), timeout=1.0)
                    if event is None:  # done sentinel
                        break
                    events_received.append(event)
            finally:
                obs._bus = original_bus

        asyncio.run(_test())

        # Should have: operation_start + 2 progress + operation_end = 4 events
        assert len(events_received) >= 3
        messages = [e["message"] for e in events_received]
        assert any("step 1" in m for m in messages)
        assert any("step 2" in m for m in messages)
