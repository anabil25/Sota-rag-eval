"""Tests for eval/runner.py — evaluation runner with mocked search and Copilot."""

import json
import os
import tempfile
from unittest.mock import AsyncMock, MagicMock, patch

import pytest

from retrieve.config import RetrieveConfig
from retrieve.db import RetrieveDB
from retrieve.eval.runner import (
    _canonical_doc_id,
    _retrieval_questions,
    aggregate_model_metrics,
    query_ai_search,
    run_evaluation,
)
from retrieve.ingest.manifest import build_document_id_aliases


class TestQueryAISearch:
    @patch("retrieve.eval.runner._get_search_client")
    def test_hybrid_query_serializes_pinned_preview_vector_controls(self, mock_get_client):
        client = MagicMock()
        client.search.return_value = iter([])
        mock_get_client.return_value = client

        query_ai_search(
            "https://test.search.windows.net",
            "test-index",
            "question",
            arch_name="hybrid",
            top_k=7,
            vector_k="23",
            vector_weight="1.5",
            vector_exhaustive=True,
            vector_filter_mode="postFilter",
            lexical_search_mode="all",
            search_fields="content,title",
        )

        kwargs = client.search.call_args.kwargs
        vector_query = kwargs["vector_queries"][0]
        assert vector_query.k == 23
        assert vector_query.weight == 1.5
        assert vector_query.exhaustive is True
        assert kwargs["top"] == 7
        assert kwargs["vector_filter_mode"] == "postFilter"
        assert kwargs["search_mode"] == "all"
        assert kwargs["search_fields"] == ["content", "title"]

    @patch("retrieve.eval.runner._get_search_client")
    @patch("retrieve.indexing.advanced.query_lightrag")
    def test_lightrag_query_uses_saved_index_contract(self, mock_query, mock_get_client):
        mock_query.return_value = (["doc-1"], 12.0)

        ids, latency = query_ai_search(
            "https://test.search.windows.net",
            "unused",
            "question",
            arch_name="lightrag",
            lightrag_mode="hybrid",
            lightrag_working_dir=".lightrag/runs/fingerprint",
            ai_services_endpoint="https://test-ai.cognitiveservices.azure.com/",
            embedding_model="embedding-deployment",
            llm_model="completion-deployment",
            lightrag_top_k="60",
            lightrag_chunk_top_k="15",
            lightrag_enable_rerank=False,
            lightrag_response_type="short-answer",
            lightrag_debug_mode="context",
        )

        assert ids == ["doc-1"]
        assert latency == 12.0
        mock_query.assert_called_once_with(
            query="question",
            mode="hybrid",
            working_dir=".lightrag/runs/fingerprint",
            ai_services_endpoint="https://test-ai.cognitiveservices.azure.com/",
            container_app_endpoint="",
            corpus_dir="corpus",
            embedding_model="embedding-deployment",
            llm_model="completion-deployment",
            top_k=60,
            chunk_top_k=15,
            enable_rerank=False,
            response_type="short-answer",
            debug_mode="context",
        )

    @patch("retrieve.eval.runner._get_search_client")
    def test_successful_query(self, mock_get_client):
        mock_client = MagicMock()
        mock_client.search.return_value = iter(
            [
                {"id": "doc1", "doc_id": "100", "metadata_storage_name": "100.md"},
                {"id": "doc2", "doc_id": "101", "metadata_storage_name": "101.md"},
            ]
        )
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

        ids, latency = query_ai_search("https://test.search.windows.net", "test-index", "query")
        assert ids == []
        assert latency > 0

    @patch("retrieve.eval.runner._get_search_client")
    def test_fallback_id_fields(self, mock_get_client):
        mock_client = MagicMock()
        mock_client.search.return_value = iter(
            [
                {"id": "fallback-id"},  # No doc_id or metadata_storage_name
                {"metadata_storage_name": "doc.md"},  # Falls back to this
            ]
        )
        mock_get_client.return_value = mock_client

        ids, _ = query_ai_search("https://test.search.windows.net", "test-index", "query")
        assert len(ids) == 2

    def test_manifest_aliases_normalize_search_and_eval_ids(self):
        manifest = {
            "documents": [
                {
                    "document_id": "100-3",
                    "source_id": "sha256:source",
                    "relative_path": "100/100-3_confidentiality.md",
                }
            ]
        }
        aliases = build_document_id_aliases(manifest)

        assert _canonical_doc_id("100-3::0", aliases) == "100-3"
        assert _canonical_doc_id("100-3_confidentiality.md", aliases) == "100-3"
        assert _canonical_doc_id("100/100-3_confidentiality.md", aliases) == "100-3"


class TestRunEvaluation:
    @patch("retrieve.eval.readiness.query_ai_search", return_value=(["100-3"], 12.5))
    def test_grounded_readiness_activates_and_persists_evidence(self, mock_query, tmp_path):
        from retrieve.eval.readiness import validate_architecture_readiness
        from retrieve.ingest.manifest import build_manifest_entry, write_corpus_manifest
        from retrieve.ingest.plugin import ConvertedDoc
        from retrieve.ingest.run import save_doc

        document = ConvertedDoc(
            "100-3",
            "Confidentiality",
            "",
            "https://example.test/100-3.htm",
            "Confidential information is protected.",
        )
        output = save_doc(document, tmp_path)
        manifest = write_corpus_manifest(
            tmp_path,
            [build_manifest_entry(document, output, tmp_path)],
        )
        cfg = RetrieveConfig(db_path=str(tmp_path / "retrieve.db"))
        cfg.corpus.output_dir = str(tmp_path)
        db = RetrieveDB(cfg.db_path)
        eval_set_id = db.create_eval_set("current")
        db.add_question(eval_set_id, "What is protected?", "direct_lookup", ["100-3::0"])
        db.upsert_generation_preferences({"active_eval_set": "current"}, "ui_session")
        db.register_architecture(
            "hybrid",
            {
                "search_endpoint": "https://test.search.windows.net",
                "index_name": "test-hybrid",
            },
        )

        results = validate_architecture_readiness(db, cfg, ["hybrid"])

        architecture = db.get_architecture("hybrid")
        assert results["hybrid"]["state"] == "succeeded"
        assert architecture["status"] == "active"
        assert architecture["config"]["query_smoke"]["corpus_fingerprint"] == manifest[
            "corpus_fingerprint"
        ]
        assert architecture["config"]["query_smoke"]["eval_set_id"] == eval_set_id
        mock_query.assert_called_once()
        db.close()

    def test_model_metrics_aggregate_raw_counters_and_recompute_rates(self):
        metrics = aggregate_model_metrics(
            [
                {
                    "azure/gpt-4.1": {
                        "attempted_request_count": 2,
                        "successful_response_count": 1,
                        "failed_response_count": 1,
                        "requests_with_retries": 1,
                        "retries": 1,
                        "responses_with_tokens": 1,
                        "total_tokens": 100,
                        "failure_rate": 0.5,
                    }
                },
                {
                    "azure/gpt-4.1": {
                        "attempted_request_count": 2,
                        "successful_response_count": 2,
                        "failed_response_count": 0,
                        "requests_with_retries": 0,
                        "retries": 0,
                        "responses_with_tokens": 2,
                        "total_tokens": 50,
                        "failure_rate": 0.0,
                    }
                },
            ]
        )["azure/gpt-4.1"]

        assert metrics["attempted_request_count"] == 4
        assert metrics["total_tokens"] == 150
        assert metrics["failure_rate"] == 0.25
        assert metrics["retry_rate"] == 0.2
        assert metrics["tokens_per_response"] == 50

    def test_retrieval_questions_exclude_inactive_and_evidence_free_rows(self):
        questions = [
            {"id": 1, "status": "active", "ground_truth_chunk_ids": ["doc-1::0"]},
            {"id": 2, "status": "inactive", "ground_truth_chunk_ids": ["doc-2::0"]},
            {"id": 3, "status": "active", "ground_truth_chunk_ids": []},
        ]

        assert [question["id"] for question in _retrieval_questions(questions)] == [1]

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
        cfg.azure.corpus_fingerprint = "corpus-fingerprint"
        cfg.corpus.output_dir = os.path.join(tmpdir, "missing-corpus")

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
        assert runs[0]["architecture_config"]["experiment_id"]
        assert runs[0]["architecture_config"]["corpus_fingerprint"] == "corpus-fingerprint"
        session = db.get_generation_preferences("ui_session")
        assert session["active_experiment_id"] == runs[0]["architecture_config"]["experiment_id"]
        assert session["active_experiment_architectures"] == ["hybrid"]

        results = db.get_results_for_run(runs[0]["id"])
        assert len(results) == 2
        assert all(r["latency_ms"] == 45.0 for r in results)
        db.close()

    @patch("retrieve.eval.runner._classify_misses", new_callable=AsyncMock, return_value=[])
    @patch("retrieve.eval.runner.query_ai_search")
    def test_graphrag_evaluation_stores_measured_model_metrics(
        self,
        mock_search,
        mock_classify,
    ):
        def query(**kwargs):
            kwargs["graphrag_metrics_sink"](
                {
                    "azure/gpt-4.1": {
                        "attempted_request_count": 1,
                        "successful_response_count": 1,
                        "failed_response_count": 0,
                        "responses_with_tokens": 1,
                        "total_tokens": 42,
                    }
                }
            )
            return ["100::0"], 25.0

        mock_search.side_effect = query
        tmpdir = tempfile.mkdtemp()
        db_path = os.path.join(tmpdir, "test.db")
        cfg = RetrieveConfig()
        cfg.db_path = db_path
        cfg.architectures = ["graphrag"]

        db = RetrieveDB(db_path)
        eval_set_id = db.create_eval_set("v1")
        db.add_question(eval_set_id, "What form?", "direct_lookup", ["100::0"])
        db.update_eval_set_counts(eval_set_id)
        db.close()

        run_evaluation(eval_set_version="v1", cfg=cfg)

        db = RetrieveDB(db_path)
        run = db.get_all_completed_runs()[0]
        metrics = run["aggregate_metrics"]["model_metrics"]["azure/gpt-4.1"]
        assert metrics["attempted_request_count"] == 1
        assert metrics["failure_rate"] == 0
        assert metrics["total_tokens"] == 42
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
        mock_response.data.content = json.dumps(
            {"failure_type": "vocabulary_mismatch", "explanation": "Different terminology"}
        )

        mock_session = AsyncMock()
        mock_session.send_and_wait.return_value = mock_response
        mock_session.__aenter__ = AsyncMock(return_value=mock_session)
        mock_session.__aexit__ = AsyncMock(return_value=False)
        mock_client.create_session = AsyncMock(return_value=mock_session)

        cfg = RetrieveConfig()
        failures = [
            {
                "question_id": 1,
                "question": "What form?",
                "expected_chunk": "chunk content",
                "wrong_chunk": "wrong content",
            }
        ]

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
                raise TimeoutError
            return await awaitable

        cfg = RetrieveConfig()
        with patch("retrieve.eval.runner.asyncio.wait_for", new=fake_wait_for):
            await _classify_misses(failures, cfg)

        assert any(
            call.args and call.args[0] == "Waiting on Copilot SDK"
            for call in mock_emit_progress.call_args_list
        )
