"""Tests for eval/runner.py — evaluation runner with mocked search and Copilot."""

import tempfile
import os
import json
import asyncio
from unittest.mock import patch, MagicMock, AsyncMock
import pytest
from retrieve.config import RetrieveConfig
from retrieve.db import RetrieveDB
from retrieve.eval.runner import query_ai_search, run_evaluation


class TestQueryAISearch:
    @patch("retrieve.eval.runner._get_search_client")
    def test_successful_query(self, mock_get_client):
        mock_client = MagicMock()
        mock_client.search.return_value = iter([
            {"id": "doc1", "doc_id": "100", "metadata_storage_name": "100.md"},
            {"id": "doc2", "doc_id": "101", "metadata_storage_name": "101.md"},
        ])
        mock_get_client.return_value = mock_client

        ids, latency = query_ai_search(
            "https://test.search.windows.net", "test-index", "What form?"
        )
        assert ids == ["100", "101"]
        assert latency > 0

    @patch("retrieve.eval.runner._get_search_client")
    def test_failed_query(self, mock_get_client):
        mock_client = MagicMock()
        mock_client.search.side_effect = Exception("Forbidden")
        mock_get_client.return_value = mock_client

        ids, latency = query_ai_search(
            "https://test.search.windows.net", "test-index", "query"
        )
        assert ids == []
        assert latency > 0

    @patch("retrieve.eval.runner._get_search_client")
    def test_fallback_id_fields(self, mock_get_client):
        mock_client = MagicMock()
        mock_client.search.return_value = iter([
            {"id": "fallback-id"},  # No doc_id or metadata_storage_name
            {"metadata_storage_name": "doc.md"},  # Falls back to this
        ])
        mock_get_client.return_value = mock_client

        ids, _ = query_ai_search(
            "https://test.search.windows.net", "test-index", "query"
        )
        assert len(ids) == 2


class TestRunEvaluation:
    @patch("retrieve.eval.runner._classify_misses", new_callable=AsyncMock, return_value=[])
    @patch("retrieve.eval.runner.query_ai_search")
    def test_run_evaluation_stores_results(self, mock_search, mock_classify):
        """End-to-end test of run_evaluation with mocked search."""
        mock_search.return_value = (["100::0", "200::0"], 45.0)

        tmpdir = tempfile.mkdtemp()
        db_path = os.path.join(tmpdir, "test.db")

        cfg = RetrieveConfig()
        cfg.db_path = db_path
        cfg.architectures = ["hybrid"]
        cfg.azure.name_prefix = "test"

        db = RetrieveDB(db_path)
        eid = db.create_eval_set("v1")
        db.add_question(eid, "What form?", "direct_lookup", ["100::0"])
        db.add_question(eid, "How long?", "process_procedure", ["101::0"])
        db.update_eval_set_counts(eid)
        db.close()

        run_evaluation(eval_set_version="v1", cfg=cfg)

        db = RetrieveDB(db_path)
        runs = db.get_all_completed_runs()
        assert len(runs) == 1
        assert runs[0]["architecture_name"] == "hybrid"
        assert runs[0]["aggregate_metrics"]["recall_at_5"] > 0

        results = db.get_results_for_run(runs[0]["id"])
        assert len(results) == 2
        assert all(r["latency_ms"] == 45.0 for r in results)
        db.close()

    @patch("retrieve.eval.runner.query_ai_search")
    def test_run_evaluation_no_eval_set(self, mock_search):
        tmpdir = tempfile.mkdtemp()
        db_path = os.path.join(tmpdir, "empty.db")
        cfg = RetrieveConfig()
        cfg.db_path = db_path
        # Should not crash — just prints error
        run_evaluation(eval_set_version="nonexistent", cfg=cfg)

    @patch("retrieve.eval.runner.query_ai_search")
    def test_query_error_marks_new_run_failed_only(self, mock_search):
        mock_search.side_effect = RuntimeError("structured evidence mismatch")
        tmpdir = tempfile.mkdtemp()
        db_path = os.path.join(tmpdir, "failure.db")
        cfg = RetrieveConfig()
        cfg.db_path = db_path
        cfg.architectures = ["graphrag"]

        db = RetrieveDB(db_path)
        eval_set_id = db.create_eval_set("v1")
        db.add_question(eval_set_id, "What policy?", "direct_lookup", ["100::0"])
        preexisting_run = db.create_run(eval_set_id, "unrelated", "test")
        db.close()

        with pytest.raises(RuntimeError, match="structured evidence mismatch"):
            run_evaluation(eval_set_version="v1", cfg=cfg)

        db = RetrieveDB(db_path)
        runs = db.get_runs_for_eval_set(eval_set_id)
        statuses = {run["architecture_name"]: run["status"] for run in runs}
        assert statuses["unrelated"] == "running"
        assert statuses["graphrag"] == "failed"
        assert db.get_run(preexisting_run)["status"] == "running"
        db.close()


class TestFailureClassification:
    @patch("retrieve.eval.runner.get_client")
    async def test_classify_misses(self, mock_get_client):
        from retrieve.eval.runner import _classify_misses

        mock_client = MagicMock()
        mock_get_client.return_value = mock_client

        mock_response = MagicMock()
        mock_response.data.content = json.dumps({
            "failure_type": "vocabulary_mismatch",
            "explanation": "Different terminology"
        })

        mock_session = AsyncMock()
        mock_session.send_and_wait.return_value = mock_response
        mock_session.__aenter__ = AsyncMock(return_value=mock_session)
        mock_session.__aexit__ = AsyncMock(return_value=False)
        mock_client.create_session = AsyncMock(return_value=mock_session)

        cfg = RetrieveConfig()
        failures = [{
            "question_id": 1,
            "question": "What form?",
            "expected_chunk": "chunk content",
            "wrong_chunk": "wrong content",
        }]

        classified = await _classify_misses(failures, cfg)
        assert len(classified) == 1
        assert classified[0]["failure_type"] == "vocabulary_mismatch"

    @patch("retrieve.eval.runner.get_client")
    async def test_classify_misses_empty(self, mock_get_client):
        from retrieve.eval.runner import _classify_misses
        cfg = RetrieveConfig()
        result = await _classify_misses([], cfg)
        assert result == []

    @patch("retrieve.eval.runner.get_client")
    @patch("retrieve.eval.runner.emit_progress")
    async def test_classify_misses_emits_heartbeat(self, mock_emit_progress, mock_get_client):
        from retrieve.eval.runner import _classify_misses

        mock_client = MagicMock()
        mock_get_client.return_value = mock_client

        mock_response = MagicMock()
        mock_response.data.content = json.dumps(
            {"miss_type": "semantic_gap", "explanation": "semantic mismatch"}
        )

        mock_session = AsyncMock()
        mock_session.send_and_wait.return_value = mock_response
        mock_session.__aenter__ = AsyncMock(return_value=mock_session)
        mock_session.__aexit__ = AsyncMock(return_value=False)
        mock_client.create_session = AsyncMock(return_value=mock_session)

        failures = [
            {
                "question_id": 1,
                "question": "Q",
                "expected_chunk": "expected",
                "wrong_chunk": "wrong",
            }
        ]

        call_count = {"n": 0}

        async def fake_wait_for(awaitable, timeout):
            call_count["n"] += 1
            if call_count["n"] == 1:
                raise asyncio.TimeoutError
            return await awaitable

        cfg = RetrieveConfig()
        with patch("retrieve.eval.runner.asyncio.wait_for", new=fake_wait_for):
            await _classify_misses(failures, cfg)

        assert any(call.args and call.args[0] == "Waiting on Copilot SDK" for call in mock_emit_progress.call_args_list)
