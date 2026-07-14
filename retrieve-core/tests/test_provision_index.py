"""Tests for GraphRAG, indexing, Search, and app-level teardown."""

import json
import os
import tempfile
from pathlib import Path
from types import SimpleNamespace
from unittest.mock import MagicMock, patch

import pytest

from retrieve.config import RetrieveConfig
from retrieve.db import RetrieveDB


class TestGraphRAGWorkerSettings:
    def test_write_settings_limits_graphrag_concurrency_and_retries(self):
        import yaml

        from retrieve.graphrag_worker.app import IndexRequest, _write_settings

        with tempfile.TemporaryDirectory() as tmpdir:
            root = Path(tmpdir)
            input_dir = root / "input"
            input_dir.mkdir()

            config = _write_settings(
                root,
                input_dir,
                IndexRequest(
                    ai_services_endpoint="https://test-ai.cognitiveservices.azure.com/",
                    llm_model="gpt-4.1",
                    embedding_model="text-embedding-3-large",
                ),
            )

            assert config.reporting.type == "file"
            assert config.reporting.connection_string is None
            assert config.output_storage.type == "file"

            settings = yaml.safe_load((root / "settings.yaml").read_text(encoding="utf-8"))

        assert settings["concurrent_requests"] == 2
        embedding = settings["embedding_models"]["default_embedding_model"]
        completion = settings["completion_models"]["default_completion_model"]
        assert embedding["rate_limit"]["tokens_per_period"] == 100_000
        assert embedding["rate_limit"]["requests_per_period"] == 100
        assert completion["rate_limit"]["tokens_per_period"] == 10_000
        assert completion["rate_limit"]["requests_per_period"] == 10
        assert embedding["retry"]["max_retries"] == 12
        assert completion["retry"]["max_delay"] == 120.0
        assert settings["extract_graph_nlp"]["normalize_edge_weights"] is True
        assert settings["prune_graph"]["min_edge_weight_pct"] == 40.0

        graphrag = pytest.importorskip("graphrag")
        assert graphrag is not None
        from graphrag.config.models.graph_rag_config import GraphRagConfig

        parsed = GraphRagConfig.model_validate(settings)
        parsed_embedding = parsed.embedding_models["default_embedding_model"]
        parsed_completion = parsed.completion_models["default_completion_model"]
        assert parsed_embedding.rate_limit is not None
        assert parsed_embedding.rate_limit.tokens_per_period == 100_000
        assert parsed_completion.rate_limit is not None
        assert parsed_completion.rate_limit.requests_per_period == 10
        assert parsed_embedding.retry.max_retries == 12
        assert parsed_completion.retry.max_delay == 120.0

    def test_worker_snapshots_official_model_metrics(self):
        from graphrag_llm.metrics import create_metrics_store

        from retrieve.graphrag.settings import (
            build_graphrag_settings,
            validate_graphrag_settings,
        )
        from retrieve.graphrag_worker.app import collect_graphrag_model_metrics

        settings = build_graphrag_settings(
            input_dir="input",
            ai_services_endpoint="https://test-ai.cognitiveservices.azure.com/",
            llm_model="metrics-test-completion",
            embedding_model="metrics-test-embedding",
        )
        config = validate_graphrag_settings(settings)
        completion = config.completion_models["default_completion_model"]
        model_id = f"{completion.model_provider}/{completion.model}"
        store = create_metrics_store(config=completion.metrics, id=model_id)
        store.clear_metrics()
        store.update_metrics(
            metrics={
                "attempted_request_count": 2,
                "successful_response_count": 2,
                "total_tokens": 123,
            }
        )

        metrics = collect_graphrag_model_metrics(config)

        assert metrics[model_id]["attempted_request_count"] == 2
        assert metrics[model_id]["successful_response_count"] == 2
        assert metrics[model_id]["total_tokens"] == 123
        store.clear_metrics()

    def test_settings_validator_rejects_silently_accepted_extras(self):
        from retrieve.graphrag.settings import (
            build_graphrag_settings,
            validate_graphrag_settings,
        )

        settings = build_graphrag_settings(
            input_dir="input",
            ai_services_endpoint="https://test-ai.cognitiveservices.azure.com/",
        )
        settings["completion_models"]["default_completion_model"]["requests_per_minute"] = 10

        with pytest.raises(ValueError, match="requests_per_minute"):
            validate_graphrag_settings(settings)

    def test_write_settings_accepts_env_overrides(self, monkeypatch):
        import yaml

        from retrieve.graphrag_worker.app import IndexRequest, _write_settings

        monkeypatch.setenv("GRAPHRAG_CONCURRENT_REQUESTS", "1")
        monkeypatch.setenv("GRAPHRAG_EMBEDDING_TOKENS_PER_MINUTE", "200000")
        monkeypatch.setenv("GRAPHRAG_EMBEDDING_REQUESTS_PER_MINUTE", "200")
        monkeypatch.setenv("GRAPHRAG_RETRY_MAX_RETRIES", "20")
        monkeypatch.setenv("GRAPHRAG_RETRY_MAX_DELAY_SECONDS", "300")

        with tempfile.TemporaryDirectory() as tmpdir:
            root = Path(tmpdir)
            input_dir = root / "input"
            input_dir.mkdir()
            _write_settings(
                root,
                input_dir,
                IndexRequest(ai_services_endpoint="https://test-ai.cognitiveservices.azure.com/"),
            )
            settings = yaml.safe_load((root / "settings.yaml").read_text(encoding="utf-8"))

        embedding = settings["embedding_models"]["default_embedding_model"]
        assert settings["concurrent_requests"] == 1
        assert embedding["rate_limit"]["tokens_per_period"] == 200_000
        assert embedding["rate_limit"]["requests_per_period"] == 200
        assert embedding["retry"]["max_retries"] == 20
        assert embedding["retry"]["max_delay"] == 300.0

    def test_write_settings_uses_persistent_blob_and_search(self):
        import yaml

        from retrieve.graphrag.settings import validate_graphrag_settings
        from retrieve.graphrag_worker.app import IndexRequest, _write_settings

        fingerprint = "a" * 64
        with tempfile.TemporaryDirectory() as tmpdir:
            root = Path(tmpdir)
            input_dir = root / "input"
            input_dir.mkdir()
            _write_settings(
                root,
                input_dir,
                IndexRequest(
                    ai_services_endpoint="https://test-ai.cognitiveservices.azure.com/",
                    search_endpoint="https://test.search.windows.net",
                ),
                storage_account="teststore",
                artifact_prefix=f"runs/{fingerprint}/job123",
                corpus_fingerprint=fingerprint,
                job_id="job12345",
            )
            settings = yaml.safe_load((root / "settings.yaml").read_text(encoding="utf-8"))

        assert settings["reporting"]["base_dir"] == (root / "logs").as_posix()
        parsed = validate_graphrag_settings(settings)
        assert parsed.output_storage.type == "blob"
        assert parsed.output_storage.base_dir == f"runs/{fingerprint}/job123/output"
        assert parsed.cache.storage is not None
        assert parsed.cache.storage.base_dir == f"cache/{fingerprint}"
        assert parsed.reporting.type == "file"
        assert parsed.reporting.connection_string is None
        assert Path(parsed.reporting.base_dir).name == "logs"
        assert Path(parsed.reporting.base_dir).parent.name == root.name
        assert parsed.vector_store.type == "azure_ai_search"
        schemas = parsed.vector_store.index_schema
        assert schemas["entity_description"].index_name == "gr-aaaaaaaa-job12345-entity"
        assert schemas["community_full_content"].vector_size == 3_072
        assert schemas["text_unit_text"].index_name.endswith("-text-unit")

    @patch("retrieve.graphrag_worker.app._set_status")
    def test_workflow_callbacks_persist_progress(self, mock_set_status):
        from retrieve.graphrag_worker.app import RetrieveWorkflowCallbacks

        status = {
            "job_id": "job123",
            "state": "running",
            "message": "",
            "started_at": "now",
            "updated_at": "now",
            "artifact_prefix": "runs/fingerprint/job123",
            "error": "",
        }
        callbacks = RetrieveWorkflowCallbacks(
            "teststore",
            "graphrag",
            status,
            min_persist_interval=0,
        )

        callbacks.pipeline_start(["create_base_text_units", "extract_graph"])
        callbacks.workflow_start("create_base_text_units", object())
        callbacks.progress(
            SimpleNamespace(
                description="Chunking documents",
                completed_items=4,
                total_items=10,
            )
        )
        callbacks.workflow_end("create_base_text_units", object())
        callbacks.pipeline_end([SimpleNamespace(workflow="create_base_text_units", error=None)])

        assert status["workflows"] == ["create_base_text_units", "extract_graph"]
        assert status["completed_workflows"] == ["create_base_text_units"]
        assert status["progress_description"] == "Chunking documents"
        assert status["progress_completed"] == 4
        assert status["progress_total"] == 10
        assert status["workflow_results"] == [{"workflow": "create_base_text_units", "error": ""}]
        assert status["heartbeat_at"]
        assert mock_set_status.call_count == 5


class TestGraphRAGSafety:
    def test_full_run_is_default_denied(self, monkeypatch):
        from retrieve.graphrag.safety import (
            FULL_RUN_APPROVAL_ENV,
            validate_graphrag_run_scope,
        )

        monkeypatch.delenv(FULL_RUN_APPROVAL_ENV, raising=False)

        with pytest.raises(RuntimeError, match="locked"):
            validate_graphrag_run_scope("full", None)

    def test_full_run_requires_explicit_approval(self, monkeypatch):
        from retrieve.graphrag.safety import (
            FULL_RUN_APPROVAL_ENV,
            validate_graphrag_run_scope,
        )

        monkeypatch.setenv(FULL_RUN_APPROVAL_ENV, "true")

        assert validate_graphrag_run_scope("full", None) is None

    @pytest.mark.parametrize(
        ("scope", "limit", "too_many"),
        [("sample", 50, 51), ("canary", 500, 501)],
    )
    def test_bounded_runs_enforce_document_caps(self, scope, limit, too_many):
        from retrieve.graphrag.safety import validate_graphrag_run_scope

        assert validate_graphrag_run_scope(scope, limit) == limit
        with pytest.raises(ValueError, match="capped"):
            validate_graphrag_run_scope(scope, too_many)
        with pytest.raises(ValueError, match="require"):
            validate_graphrag_run_scope(scope, None)

    def test_current_artifact_prefix_is_rejected(self):
        from retrieve.graphrag.safety import validate_graphrag_artifact_prefix

        with pytest.raises(ValueError, match="indexes/current"):
            validate_graphrag_artifact_prefix("/indexes/current/")

        validate_graphrag_artifact_prefix("indexes/run-123")

    def test_worker_endpoint_enforces_full_run_lock(self, monkeypatch):
        from fastapi import BackgroundTasks, HTTPException

        from retrieve.graphrag.safety import FULL_RUN_APPROVAL_ENV
        from retrieve.graphrag_worker.app import IndexRequest, start_index

        monkeypatch.delenv(FULL_RUN_APPROVAL_ENV, raising=False)

        with pytest.raises(HTTPException) as exc_info:
            start_index(IndexRequest(), BackgroundTasks())

        assert exc_info.value.status_code == 423
        assert "locked" in str(exc_info.value.detail)

    @patch("retrieve.graphrag_worker.app._blob_service")
    def test_worker_download_stops_at_document_cap(self, mock_blob_service, tmp_path):
        from types import SimpleNamespace

        from retrieve.graphrag_worker.app import _download_corpus

        container = mock_blob_service.return_value.get_container_client.return_value
        container.list_blobs.return_value = [
            SimpleNamespace(name="one.md"),
            SimpleNamespace(name="two.md"),
            SimpleNamespace(name="three.md"),
        ]
        container.download_blob.return_value.readall.return_value = b"content"

        count = _download_corpus(
            "teststore",
            "corpus",
            "",
            tmp_path,
            max_documents=2,
        )

        assert count == 2
        assert sorted(path.name for path in tmp_path.glob("*.md")) == ["one.md", "two.md"]
        assert container.download_blob.call_count == 2

    @patch("retrieve.graphrag_worker.app._blob_service")
    def test_worker_downloads_only_manifest_managed_paths(self, mock_blob_service, tmp_path):
        from retrieve.graphrag_worker.app import _download_corpus

        container = mock_blob_service.return_value.get_container_client.return_value
        container.download_blob.return_value.readall.return_value = b"content"

        count = _download_corpus(
            "teststore",
            "corpus",
            "",
            tmp_path,
            managed_paths=["100/managed.md"],
        )

        assert count == 1
        container.list_blobs.assert_not_called()
        container.download_blob.assert_called_once_with("100/managed.md")
        assert (tmp_path / "100" / "managed.md").read_bytes() == b"content"

    @patch("retrieve.indexing.advanced.requests.post")
    def test_cloud_launch_is_bound_to_manifest_and_immutable_run(self, mock_post, tmp_path):
        from retrieve.indexing.advanced import run_graphrag_indexing
        from retrieve.ingest.manifest import build_manifest_entry, write_corpus_manifest
        from retrieve.ingest.plugin import ConvertedDoc
        from retrieve.ingest.run import save_doc

        doc = ConvertedDoc(
            "100",
            "Policy",
            "",
            "https://example.test/100.htm",
            "Policy body",
        )
        output = save_doc(doc, tmp_path)
        manifest = write_corpus_manifest(
            tmp_path,
            [build_manifest_entry(doc, output, tmp_path)],
        )
        response = MagicMock()
        response.json.return_value = {"job_id": "job123"}
        mock_post.return_value = response

        result = run_graphrag_indexing(
            corpus_dir=str(tmp_path),
            ai_services_endpoint="https://test-ai.cognitiveservices.azure.com/",
            search_endpoint="https://test.search.windows.net",
            storage_account="teststore",
            graph_worker_endpoint="https://worker.example",
        )

        payload = mock_post.call_args.kwargs["json"]
        fingerprint = manifest["corpus_fingerprint"]
        assert payload["corpus_fingerprint"] == fingerprint
        assert payload["search_endpoint"] == "https://test.search.windows.net"
        assert payload["run_scope"] == "sample"
        assert payload["max_documents"] == 50
        assert "output_prefix" not in payload
        assert result["graph_worker_artifact_prefix"] == f"runs/{fingerprint}/job123"
        assert result["graph_worker_run_scope"] == "sample"
        assert result["graph_worker_max_documents"] == 50

    @patch("retrieve.indexing.advanced.uuid.uuid4")
    @patch("retrieve.indexing.advanced.start_container_job")
    def test_container_job_launch_is_bound_to_immutable_run(self, mock_start, mock_uuid, tmp_path):
        from types import SimpleNamespace

        from retrieve.indexing.advanced import run_graphrag_indexing
        from retrieve.ingest.manifest import build_manifest_entry, write_corpus_manifest
        from retrieve.ingest.plugin import ConvertedDoc
        from retrieve.ingest.run import save_doc

        doc = ConvertedDoc(
            "100",
            "Policy",
            "",
            "https://example.test/100.htm",
            "Policy body",
        )
        output = save_doc(doc, tmp_path)
        manifest = write_corpus_manifest(
            tmp_path,
            [build_manifest_entry(doc, output, tmp_path)],
        )
        mock_uuid.return_value = SimpleNamespace(hex="job123")
        mock_start.return_value = "graph-job-abc"

        result = run_graphrag_indexing(
            corpus_dir=str(tmp_path),
            ai_services_endpoint="https://test-ai.cognitiveservices.azure.com/",
            search_endpoint="https://test.search.windows.net",
            storage_account="teststore",
            graph_job_name="azgrjtest",
            resource_group="rg-test",
            subscription_id="sub-test",
            chunk_size=100,
            chunk_overlap=20,
            required_document_ids=["100"],
        )

        fingerprint = manifest["corpus_fingerprint"]
        environment = mock_start.call_args.kwargs["environment"]
        assert mock_start.call_args.kwargs["job_name"] == "azgrjtest"
        assert mock_start.call_args.kwargs["resource_group"] == "rg-test"
        assert mock_start.call_args.kwargs["subscription_id"] == "sub-test"
        assert "GRAPH_WORKER_MODE=index" in environment
        assert "GRAPH_WORKER_JOB_ID=job123" in environment
        assert f"CORPUS_FINGERPRINT={fingerprint}" in environment
        assert f"GRAPH_OUTPUT_PREFIX=runs/{fingerprint}/job123" in environment
        assert "GRAPHRAG_RUN_SCOPE=sample" in environment
        assert "GRAPHRAG_MAX_DOCUMENTS=50" in environment
        assert "GRAPHRAG_CHUNK_SIZE=100" in environment
        assert "GRAPHRAG_CHUNK_OVERLAP=20" in environment
        selection = next(
            value.split("=", 1)[1]
            for value in environment
            if value.startswith("GRAPHRAG_SAMPLE_SELECTION=")
        )
        from retrieve.graphrag_worker.protocol import decode_payload

        assert decode_payload(selection) == {"required_document_ids": ["100"]}
        assert result["graph_job_execution_name"] == "graph-job-abc"
        assert result["graph_worker_artifact_prefix"] == (f"runs/{fingerprint}/job123")
        assert result["graph_worker_status_blob"] == "jobs/job123/status.json"
        assert result["graph_worker_chunk_size"] == 100
        assert result["graph_worker_chunk_overlap"] == 20
        assert result["graph_worker_required_document_ids"] == ["100"]

    def test_sample_selection_includes_required_documents_and_spans_manifest(self):
        from retrieve.graphrag_worker.app import select_graphrag_documents

        documents = [
            {"document_id": f"doc-{index}", "relative_path": f"{index:02d}.md"}
            for index in range(10)
        ]

        selected = select_graphrag_documents(
            {"documents": documents},
            max_documents=4,
            required_document_ids=["doc-5"],
        )

        selected_ids = {document["document_id"] for document in selected}
        assert len(selected) == 4
        assert "doc-5" in selected_ids
        assert selected_ids & {"doc-0", "doc-1"}
        assert selected_ids & {"doc-8", "doc-9"}

    def test_sample_selection_needs_no_eval_document_ids(self):
        from retrieve.graphrag_worker.app import select_graphrag_documents

        documents = [
            {"document_id": f"doc-{index}", "relative_path": f"{index:02d}.md"}
            for index in range(10)
        ]

        selected = select_graphrag_documents(
            {"documents": documents},
            max_documents=4,
        )

        selected_ids = {document["document_id"] for document in selected}
        assert len(selected) == 4
        assert selected_ids & {"doc-0", "doc-1"}
        assert selected_ids & {"doc-8", "doc-9"}

    def test_local_indexing_uses_public_api_not_cli(self, monkeypatch, tmp_path):
        from types import SimpleNamespace
        from unittest.mock import AsyncMock

        import graphrag.api

        from retrieve.graphrag.safety import FULL_RUN_APPROVAL_ENV
        from retrieve.indexing.advanced import run_graphrag_indexing
        from retrieve.ingest.manifest import build_manifest_entry, write_corpus_manifest
        from retrieve.ingest.plugin import ConvertedDoc
        from retrieve.ingest.run import save_doc

        doc = ConvertedDoc(
            "100",
            "Policy",
            "",
            "https://example.test/100.htm",
            "Policy body",
        )
        output = save_doc(doc, tmp_path)
        write_corpus_manifest(
            tmp_path,
            [build_manifest_entry(doc, output, tmp_path)],
        )
        build_index = AsyncMock(return_value=[SimpleNamespace(workflow="pipeline", error=None)])
        monkeypatch.setattr(graphrag.api, "build_index", build_index)
        monkeypatch.setenv(FULL_RUN_APPROVAL_ENV, "true")
        monkeypatch.setenv("RETRIEVE_ALLOW_LOCAL_GRAPHRAG", "true")

        with patch("retrieve.indexing.advanced.subprocess.run") as subprocess_run:
            run_graphrag_indexing(
                corpus_dir=str(tmp_path),
                ai_services_endpoint="https://test-ai.cognitiveservices.azure.com/",
                output_dir=str(tmp_path / "project"),
                run_scope="full",
                max_documents=None,
            )

        build_index.assert_awaited_once()
        subprocess_run.assert_not_called()


class TestTeardown:
    def test_teardown_marks_status(self):
        tmpdir = tempfile.mkdtemp()
        db_path = os.path.join(tmpdir, "test.db")

        db = RetrieveDB(db_path)
        db.register_architecture("keyword", {"search_endpoint": "https://x", "index_name": "x"})
        db.register_architecture("hybrid", {"search_endpoint": "https://x", "index_name": "x"})
        # Manually set status to provisioned
        db.conn.execute("UPDATE architectures SET status = 'provisioned'")
        db.conn.commit()
        db.close()

        cfg = RetrieveConfig()
        cfg.db_path = db_path
        cfg.architectures = ["hybrid"]

        from retrieve.provision.teardown import teardown

        with patch("retrieve.provision.teardown._delete_search_resources"):
            teardown(keep=["hybrid"], cfg=cfg)

        db = RetrieveDB(db_path)
        kw = db.get_architecture("keyword")
        hy = db.get_architecture("hybrid")
        assert kw["status"] == "torn_down"
        assert hy["status"] == "active"
        db.close()

    def test_teardown_nothing_provisioned(self):
        tmpdir = tempfile.mkdtemp()
        db_path = os.path.join(tmpdir, "empty.db")
        cfg = RetrieveConfig()
        cfg.db_path = db_path
        cfg.architectures = ["hybrid"]

        from retrieve.provision.teardown import teardown

        # Should not crash
        teardown(keep=None, cfg=cfg)

    def test_teardown_failure_does_not_mark_architecture_removed(self, tmp_path):
        db_path = tmp_path / "retrieve.db"
        db = RetrieveDB(db_path)
        db.register_architecture(
            "keyword", {"search_endpoint": "https://x", "index_name": "keyword"}
        )
        db.conn.execute("UPDATE architectures SET status = 'provisioned'")
        db.conn.commit()
        db.close()
        cfg = RetrieveConfig(db_path=str(db_path), architectures=["keyword"])

        from retrieve.provision.teardown import teardown

        with (
            patch(
                "retrieve.provision.teardown._delete_search_resources",
                side_effect=RuntimeError("delete failed"),
            ),
            pytest.raises(RuntimeError, match="delete failed"),
        ):
            teardown(keep=[], cfg=cfg)

        db = RetrieveDB(db_path)
        assert db.get_architecture("keyword")["status"] == "provisioned"
        db.close()

    @patch("retrieve.provision.teardown._delete_search_resources")
    @patch("retrieve.provision.teardown.requests.delete")
    @patch("retrieve.indexing.search_index._search_rest_headers", return_value={})
    @patch("azure.identity.DefaultAzureCredential")
    def test_agentic_teardown_removes_kb_source_and_base_index(
        self,
        mock_credential,
        mock_headers,
        mock_delete,
        mock_delete_search,
    ):
        from retrieve.provision.teardown import _delete_agentic_resources

        mock_delete.return_value = SimpleNamespace(status_code=204, text="")

        _delete_agentic_resources(
            "https://test.search.windows.net",
            "test-agentic-kb",
        )

        urls = [call.args[0] for call in mock_delete.call_args_list]
        assert any("knowledgebases('test-agentic-kb')" in url for url in urls)
        assert any("knowledgesources('test-agentic-kb-base-ks')" in url for url in urls)
        mock_delete_search.assert_called_once_with(
            "https://test.search.windows.net", "test-agentic-kb-base"
        )

    @patch("azure.search.documents.indexes.SearchIndexClient")
    @patch("azure.identity.DefaultAzureCredential")
    def test_graphrag_teardown_deletes_only_matching_corpus_indexes(
        self,
        mock_credential,
        mock_client_type,
    ):
        from retrieve.provision.teardown import _delete_graphrag_search_resources

        client = mock_client_type.return_value
        matching = SimpleNamespace(name="gr-ffffffff-job123-entity")
        winner = SimpleNamespace(name="ret-token-hybrid-reranker")
        client.list_indexes.side_effect = [[matching, winner], [winner]]

        _delete_graphrag_search_resources(
            "https://test.search.windows.net",
            {"corpus_fingerprint": "f" * 64},
        )

        client.delete_index.assert_called_once_with(matching.name)

    @patch("retrieve.provision.teardown._az_cmd")
    def test_graphrag_blob_retention_requires_owned_prefixes(
        self,
        mock_az,
    ):
        from retrieve.provision.teardown import _verify_graphrag_blob_retention

        mock_az.return_value = SimpleNamespace(
            returncode=0,
            stderr="",
            stdout=json.dumps(
                {
                    "policy": {
                        "rules": [
                            {
                                "name": "retrieve-delete-graphrag-artifacts",
                                "enabled": True,
                                "definition": {
                                    "actions": {
                                        "baseBlob": {
                                            "delete": {
                                                "daysAfterModificationGreaterThan": 30
                                            }
                                        }
                                    },
                                    "filters": {
                                        "prefixMatch": [
                                            "graphrag/runs/",
                                            "graphrag/cache/",
                                            "graphrag/jobs/",
                                        ]
                                    },
                                },
                            }
                        ]
                    }
                }
            ),
        )

        _verify_graphrag_blob_retention(
            {
                "storage_account": "teststore",
                "resource_group": "rg-test",
                "subscription_id": "sub-test",
                "graph_output_container": "graphrag",
                "corpus_container": "corpus",
            }
        )

        command = mock_az.call_args.args[0]
        assert command[0:4] == ["storage", "account", "management-policy", "show"]

    def test_lightrag_teardown_requires_marker_and_removes_only_root(self, tmp_path):
        from retrieve.provision.teardown import _delete_lightrag_state

        root = tmp_path / "state"
        active = root / "runs" / "fingerprint"
        active.mkdir(parents=True)
        (active / "retrieve-index.json").write_text(
            json.dumps({"corpus_fingerprint": "f" * 64}), encoding="utf-8"
        )
        unrelated = tmp_path / "unrelated.txt"
        unrelated.write_text("keep", encoding="utf-8")

        _delete_lightrag_state(
            {
                "lightrag_working_root": str(root),
                "lightrag_working_dir": str(active),
                "representative_corpus_fingerprint": "f" * 64,
            }
        )

        assert not root.exists()
        assert unrelated.read_text(encoding="utf-8") == "keep"

    def test_graph_runtime_teardown_blocks_protected_resource_group(self):
        from retrieve.provision.teardown import _delete_graph_runtime

        with pytest.raises(RuntimeError, match="Protected resource group"):
            _delete_graph_runtime({"resource_group": "rg-ret-test2"})

    @patch("retrieve.provision.teardown._az_json", return_value=[])
    @patch("retrieve.provision.teardown._az_cmd")
    def test_graph_support_teardown_uses_exact_derived_names(self, mock_az, mock_az_json):
        from retrieve.provision.teardown import _delete_graph_support_resources

        mock_az.side_effect = [
            SimpleNamespace(
                returncode=0,
                stdout=json.dumps({"principalId": "principal-1"}),
                stderr="",
            ),
            SimpleNamespace(returncode=0, stdout="", stderr=""),
            SimpleNamespace(returncode=0, stdout="", stderr=""),
            SimpleNamespace(returncode=0, stdout="", stderr=""),
        ]

        _delete_graph_support_resources(
            {
                "resource_group": "rg-test",
                "subscription_id": "sub-test",
                "resource_token": "token",
                "location": "North Central US",
            }
        )

        commands = [call.args[0] for call in mock_az.call_args_list]
        assert commands[0][0:4] == ["identity", "show", "--name", "azidtoken"]
        assert "azvnettoken" in commands[2]
        assert "azvnettoken-container-apps-nsg-northcentralus" in commands[3]
        mock_az_json.assert_called_once()

    def test_teardown_promotes_exact_selected_winner_run(self, tmp_path):
        db_path = tmp_path / "retrieve.db"
        db = RetrieveDB(db_path)
        eval_set_id = db.create_eval_set("v1")
        architecture_id = db.register_architecture(
            "hybrid-reranker",
            {"index_name": "winner-index", "corpus_fingerprint": "f" * 64},
        )
        run_id = db.create_run(
            eval_set_id,
            "hybrid-reranker",
            "sota",
            {
                "candidate_base": "hybrid-reranker",
                "experiment_id": "experiment-1",
                "corpus_fingerprint": "f" * 64,
                "semantic_reranker": "on",
            },
            architecture_id,
        )
        db.complete_run(run_id, {"ndcg_at_10": 0.8})
        db.conn.execute("UPDATE architectures SET status = 'provisioned'")
        db.upsert_generation_preferences(
            {
                "final_winner": "hybrid-reranker",
                "selected_run_id": run_id,
                "final_eval_set_id": eval_set_id,
                "final_corpus_fingerprint": "f" * 64,
            },
            "ui_session",
        )
        db.close()
        cfg = RetrieveConfig(
            db_path=str(db_path),
            architectures=["hybrid-reranker"],
        )

        from retrieve.provision.teardown import teardown

        teardown(keep=["hybrid-reranker"], cfg=cfg)

        db = RetrieveDB(db_path)
        winner = db.get_architecture("hybrid-reranker")
        assert winner["status"] == "active"
        assert winner["config"]["semantic_reranker"] == "on"
        assert winner["config"]["selected_run_id"] == run_id
        assert winner["config"]["selected_metrics"]["ndcg_at_10"] == 0.8
        db.close()


class TestIndexOrchestrator:
    def test_graph_sample_contract_uses_active_grounded_eval_evidence(self, tmp_path):
        from retrieve.indexing.run import _grounded_eval_sample_contract
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
        db = RetrieveDB(tmp_path / "retrieve.db")
        old_eval_id = db.create_eval_set("old")
        db.add_question(old_eval_id, "Old?", "direct_lookup", [])
        eval_set_id = db.create_eval_set("current")
        db.add_question(eval_set_id, "Grounded?", "direct_lookup", ["100-3::0"])
        db.add_question(
            eval_set_id,
            "Inactive?",
            "direct_lookup",
            ["missing::0"],
            status="inactive",
        )
        db.upsert_generation_preferences(
            {"active_eval_set": "current"}, scope_key="ui_session"
        )

        contract = _grounded_eval_sample_contract(db, str(tmp_path))

        assert contract == {
            "eval_set_id": eval_set_id,
            "eval_set_version": "current",
            "corpus_fingerprint": manifest["corpus_fingerprint"],
            "required_document_ids": ["100-3"],
        }
        db.close()

    @patch("retrieve.indexing.run.time.sleep")
    @patch("retrieve.indexing.run.upload_corpus")
    @patch("retrieve.indexing.run.create_index_for_architecture")
    @patch("retrieve.indexing.run.wait_for_indexer")
    def test_index_reuses_attested_private_corpus(
        self,
        mock_wait,
        mock_create,
        mock_upload,
        mock_sleep,
        tmp_path,
    ):
        from retrieve.ingest.manifest import build_manifest_entry, write_corpus_manifest
        from retrieve.ingest.plugin import ConvertedDoc
        from retrieve.ingest.run import save_doc

        document = ConvertedDoc(
            "100",
            "Policy",
            "",
            "https://example.test/100.htm",
            "Policy body",
        )
        output = save_doc(document, tmp_path)
        manifest = write_corpus_manifest(
            tmp_path,
            [build_manifest_entry(document, output, tmp_path)],
        )
        db_path = tmp_path / "retrieve.db"
        db = RetrieveDB(db_path)
        db.register_architecture(
            "hybrid",
            {
                "search_endpoint": "https://test.search.windows.net",
                "index_name": "test-hybrid",
                "storage_account": "teststore",
                "ai_services_endpoint": "https://test-ai.openai.azure.com",
                "corpus_fingerprint": manifest["corpus_fingerprint"],
            },
        )
        db.conn.execute("UPDATE architectures SET status = 'provisioned'")
        db.conn.commit()
        db.close()
        mock_wait.return_value = {
            "status": "success",
            "item_count": 1,
            "failed_count": 0,
            "errors": [],
        }
        cfg = RetrieveConfig()
        cfg.db_path = db_path
        cfg.architectures = ["hybrid"]
        cfg.corpus.output_dir = str(tmp_path)

        from retrieve.indexing.run import index_corpus

        index_corpus(cfg)

        mock_upload.assert_not_called()
        mock_create.assert_called_once()

    @patch("retrieve.indexing.run.time.sleep")
    @patch("retrieve.indexing.run.upload_corpus")
    @patch("retrieve.indexing.run.create_index_for_architecture")
    @patch("retrieve.indexing.run.wait_for_indexer")
    def test_index_corpus_flow(self, mock_wait, mock_create, mock_upload, mock_sleep):
        mock_upload.return_value = 10
        mock_wait.return_value = {
            "status": "success",
            "item_count": 10,
            "failed_count": 0,
            "errors": [],
        }

        tmpdir = tempfile.mkdtemp()
        db_path = os.path.join(tmpdir, "test.db")

        db = RetrieveDB(db_path)
        db.register_architecture(
            "hybrid",
            {
                "search_endpoint": "https://test.search.windows.net",
                "index_name": "test-hybrid",
                "storage_account": "teststore",
                "ai_services_endpoint": "https://test-ai.openai.azure.com",
            },
        )
        db.conn.execute("UPDATE architectures SET status = 'provisioned'")
        db.conn.commit()
        db.close()

        cfg = RetrieveConfig()
        cfg.db_path = db_path
        cfg.architectures = ["hybrid"]
        cfg.corpus.output_dir = tmpdir

        from retrieve.indexing.run import index_corpus

        index_corpus(cfg)

        mock_upload.assert_called_once()
        mock_create.assert_called_once()

        # Should update status to active
        db = RetrieveDB(db_path)
        arch = db.get_architecture("hybrid")
        assert arch["status"] == "active"
        db.close()

    @patch("retrieve.indexing.run.time.sleep")
    @patch("retrieve.indexing.run.upload_corpus", return_value=10)
    @patch("retrieve.indexing.run.create_index_for_architecture")
    @patch("retrieve.indexing.run.rerun_indexer")
    @patch("retrieve.indexing.run.wait_for_indexer")
    def test_exhausted_indexer_retries_mark_architecture_failed(
        self,
        mock_wait,
        mock_rerun,
        mock_create,
        mock_upload,
        mock_sleep,
    ):
        mock_wait.return_value = {
            "status": "transientFailure",
            "item_count": 10,
            "failed_count": 10,
            "errors": [{"message": "403 Forbidden"}],
        }
        tmpdir = tempfile.mkdtemp()
        db_path = os.path.join(tmpdir, "test.db")
        db = RetrieveDB(db_path)
        db.register_architecture(
            "hybrid",
            {
                "search_endpoint": "https://test.search.windows.net",
                "index_name": "test-hybrid",
                "storage_account": "teststore",
                "ai_services_endpoint": "https://test-ai.openai.azure.com",
            },
        )
        db.conn.execute("UPDATE architectures SET status = 'provisioned'")
        db.conn.commit()
        db.close()

        cfg = RetrieveConfig()
        cfg.db_path = db_path
        cfg.architectures = ["hybrid"]
        cfg.corpus.output_dir = tmpdir

        from retrieve.indexing.run import index_corpus

        with pytest.raises(RuntimeError, match="Indexing failed for architecture.*hybrid"):
            index_corpus(cfg)

        assert mock_rerun.call_count == 5
        db = RetrieveDB(db_path)
        arch = db.get_architecture("hybrid")
        assert arch["status"] == "failed"
        db.close()

    def test_index_nothing_provisioned(self):
        tmpdir = tempfile.mkdtemp()
        db_path = os.path.join(tmpdir, "empty.db")
        cfg = RetrieveConfig()
        cfg.db_path = db_path
        cfg.architectures = ["hybrid"]

        from retrieve.indexing.run import index_corpus

        # Should not crash
        index_corpus(cfg)

    @patch("retrieve.indexing.run.create_index_for_architecture")
    @patch("retrieve.indexing.run.upload_corpus")
    def test_index_dry_run_stops_before_index_creation(self, mock_upload, mock_create):
        from retrieve.indexing.blob_upload import BlobMirrorPlan
        from retrieve.indexing.run import index_corpus

        tmpdir = tempfile.mkdtemp()
        db_path = os.path.join(tmpdir, "test.db")
        db = RetrieveDB(db_path)
        db.register_architecture(
            "keyword",
            {
                "search_endpoint": "https://test.search.windows.net",
                "index_name": "test-keyword",
                "storage_account": "teststore",
            },
        )
        db.conn.execute("UPDATE architectures SET status = 'provisioned'")
        db.conn.commit()
        db.close()
        mock_upload.return_value = BlobMirrorPlan(
            corpus_fingerprint="abc",
            document_count=2,
            uploads=("101/new.md",),
            deletes=(),
            unchanged=("100/existing.md",),
            unmanaged=(),
            remote_manifest_found=True,
        )
        cfg = RetrieveConfig()
        cfg.db_path = db_path
        cfg.architectures = ["keyword"]
        cfg.corpus.output_dir = tmpdir

        result = index_corpus(cfg, dry_run=True)

        assert result["dry_run"] is True
        assert result["blob_mirror_plan"]["uploads"] == ["101/new.md"]
        mock_upload.assert_called_once_with(tmpdir, "teststore", dry_run=True)
        mock_create.assert_not_called()


class TestSearchIndexBuilder:
    def test_indexer_wait_default_covers_large_corpus(self):
        from inspect import signature

        from retrieve.indexing.search_index import wait_for_indexer

        assert signature(wait_for_indexer).parameters["timeout"].default == 3600

    @patch("retrieve.indexing.search_index._search_rest_put")
    @patch("retrieve.indexing.search_index.SearchIndexerClient")
    @patch("retrieve.indexing.search_index.SearchIndexClient")
    @patch("retrieve.indexing.search_index.DefaultAzureCredential")
    def test_create_keyword_index(
        self, mock_cred, mock_idx_client, mock_idxr_client, mock_rest_put
    ):
        from retrieve.indexing.search_index import create_index_for_architecture

        create_index_for_architecture(
            "keyword", "https://test.search.windows.net", "test-keyword", "", "", "teststore"
        )
        # Should have created: data source, index, indexer + run
        mock_idxr_client.return_value.create_or_update_data_source_connection.assert_called_once()
        mock_idx_client.return_value.create_or_update_index.assert_called_once()
        indexer_payload = mock_rest_put.call_args.args[2]
        assert indexer_payload["parameters"]["configuration"]["executionEnvironment"] == "private"

    @patch("retrieve.indexing.search_index._search_rest_put")
    @patch("retrieve.indexing.search_index.SearchIndexerClient")
    @patch("retrieve.indexing.search_index.SearchIndexClient")
    @patch("retrieve.indexing.search_index.DefaultAzureCredential")
    def test_create_hybrid_index(
        self, mock_cred, mock_idx_client, mock_idxr_client, mock_rest_put
    ):
        from retrieve.indexing.search_index import create_index_for_architecture

        create_index_for_architecture(
            "hybrid",
            "https://test.search.windows.net",
            "test-hybrid",
            "https://test-ai.openai.azure.com",
            "text-embedding-3-large",
            "teststore",
        )
        # Should have created: data source, skillset, index, indexer
        mock_idxr_client.return_value.create_or_update_data_source_connection.assert_called_once()
        mock_idxr_client.return_value.create_or_update_skillset.assert_called_once()
        mock_idx_client.return_value.create_or_update_index.assert_called_once()
        indexer_payload = mock_rest_put.call_args.args[2]
        assert indexer_payload["parameters"]["configuration"]["executionEnvironment"] == "private"

    @patch("retrieve.indexing.search_index._search_rest_put")
    @patch("retrieve.indexing.search_index.SearchIndexerClient")
    @patch("retrieve.indexing.search_index.SearchIndexClient")
    @patch("retrieve.indexing.search_index.DefaultAzureCredential")
    def test_create_hybrid_reranker_index(
        self, mock_cred, mock_idx_client, mock_idxr_client, mock_rest_put
    ):
        from retrieve.indexing.search_index import create_index_for_architecture

        create_index_for_architecture(
            "hybrid-reranker",
            "https://test.search.windows.net",
            "test-hr",
            "https://test-ai.openai.azure.com",
            "text-embedding-3-large",
            "teststore",
        )
        # Same as hybrid but with semantic config
        mock_idx_client.return_value.create_or_update_index.assert_called_once()
        indexer_payload = mock_rest_put.call_args.args[2]
        assert indexer_payload["parameters"]["configuration"]["executionEnvironment"] == "private"

    def test_unimplemented_architecture(self):
        from retrieve.indexing.search_index import create_index_for_architecture

        # Should not crash — just prints warning
        create_index_for_architecture(
            "graphrag", "https://test.search.windows.net", "test-gr", "", "", ""
        )

    def test_agentic_query_requests_and_maps_reference_source_data(self):
        from retrieve.indexing.advanced import query_agentic_kb

        reference = SimpleNamespace(
            as_dict=lambda: {
                "doc_key": "chunk-key",
                "id": "0",
                "source_data": {"doc_id": "714-1_alaska_residency.md"},
            },
        )
        kb_client = MagicMock()
        kb_client.retrieve.return_value = SimpleNamespace(references=[reference])
        with (
            patch(
                "azure.search.documents.knowledgebases.KnowledgeBaseRetrievalClient",
                return_value=kb_client,
            ),
            patch("retrieve.indexing.advanced.DefaultAzureCredential"),
        ):
            document_ids, latency_ms = query_agentic_kb(
                "https://test.search.windows.net",
                "test-agentic-kb",
                "What is residency?",
                reasoning_effort="medium",
                output_mode="extractiveData",
                max_runtime_seconds=45,
                include_activity=False,
            )

        assert document_ids == ["714-1_alaska_residency.md"]
        request = kb_client.retrieve.call_args.kwargs["retrieval_request"]
        assert request.retrieval_reasoning_effort.kind == "medium"
        assert request.output_mode.value == "extractiveData"
        assert request.max_runtime_in_seconds == 45
        assert request.include_activity is False
        assert latency_ms >= 0
        request = kb_client.retrieve.call_args.kwargs["retrieval_request"]
        params = request.knowledge_source_params[0]
        assert params.knowledge_source_name == "test-agentic-kb-base-ks"
        assert params.include_references is True
        assert params.include_reference_source_data is True

    def test_foundry_cohere_multivector_uses_rest_payloads(self):
        from retrieve.indexing.advanced import create_multivector_index

        with (
            patch("retrieve.indexing.advanced.DefaultAzureCredential"),
            patch("retrieve.indexing.advanced.SearchIndexClient"),
            patch("retrieve.indexing.advanced.SearchIndexerClient") as mock_indexer_client,
            patch("retrieve.indexing.advanced._put_search_resource") as mock_put,
        ):
            create_multivector_index(
                endpoint="https://test.search.windows.net",
                index_name="test-mv",
                ai_services_endpoint="https://test-ai.openai.azure.com",
                cohere_uri="https://cohere.eastus.models.ai.azure.com/",
                cohere_model_name="Cohere-embed-v3-english",
                cohere_key="secret-key",
            )

        assert mock_put.call_count == 3
        index_payload = mock_put.call_args_list[0].args[2]
        assert index_payload["fields"][-1]["dimensions"] == 1024
        vectorizer = index_payload["vectorSearch"]["vectorizers"][0]
        assert vectorizer["kind"] == "aml"
        assert vectorizer["amlParameters"]["uri"] == "https://cohere.eastus.models.ai.azure.com"
        assert vectorizer["amlParameters"]["key"] == "secret-key"
        assert vectorizer["amlParameters"]["modelName"] == "Cohere-embed-v3-english"

        skillset_payload = mock_put.call_args_list[1].args[2]
        aml_skill = skillset_payload["skills"][1]
        assert aml_skill["@odata.type"] == "#Microsoft.Skills.Custom.AmlSkill"
        assert aml_skill["uri"] == "https://cohere.eastus.models.ai.azure.com/v1/embed"
        assert aml_skill["key"] == "secret-key"
        mapping = skillset_payload["indexProjections"]["selectors"][0]["mappings"][1]
        assert mapping["source"] == "/document/chunks/*/aml_vector_data/float/0"

        indexer_payload = mock_put.call_args_list[2].args[2]
        assert indexer_payload["parameters"]["configuration"]["executionEnvironment"] == "private"

        mock_indexer_client.return_value.create_or_update_skillset.assert_not_called()
        mock_indexer_client.return_value.create_or_update_indexer.assert_not_called()

    def test_foundry_cohere_multivector_requires_key(self):
        from retrieve.indexing.advanced import create_multivector_index

        with pytest.raises(ValueError, match="cohere_key is required"):
            create_multivector_index(
                endpoint="https://test.search.windows.net",
                index_name="test-mv",
                ai_services_endpoint="https://test-ai.openai.azure.com",
                cohere_uri="https://cohere.eastus.models.ai.azure.com/",
                cohere_model_name="Cohere-embed-v3-english",
            )

    def test_custom_web_api_multivector_uses_rest_payloads(self):
        from retrieve.indexing.advanced import create_multivector_index

        with (
            patch("retrieve.indexing.advanced.DefaultAzureCredential"),
            patch("retrieve.indexing.advanced.SearchIndexClient"),
            patch("retrieve.indexing.advanced.SearchIndexerClient") as mock_indexer_client,
            patch("retrieve.indexing.advanced._put_search_resource") as mock_put,
        ):
            create_multivector_index(
                endpoint="https://test.search.windows.net",
                index_name="test-mv",
                ai_services_endpoint="https://test-ai.openai.azure.com",
                embedding_model="bge-m3",
                custom_embedding_uri="https://embeddings.example.com/vectorize",
                custom_embedding_key="secret-key",
                custom_embedding_header_name="x-api-key",
            )

        assert mock_put.call_count == 3
        index_payload = mock_put.call_args_list[0].args[2]
        assert index_payload["fields"][-1]["dimensions"] == 1024
        vectorizer = index_payload["vectorSearch"]["vectorizers"][0]
        assert vectorizer["kind"] == "customWebApi"
        assert vectorizer["customWebApiParameters"]["uri"] == (
            "https://embeddings.example.com/vectorize"
        )
        assert vectorizer["customWebApiParameters"]["httpHeaders"] == {"x-api-key": "secret-key"}

        skillset_payload = mock_put.call_args_list[1].args[2]
        web_api_skill = skillset_payload["skills"][1]
        assert web_api_skill["@odata.type"] == "#Microsoft.Skills.Custom.WebApiSkill"
        assert web_api_skill["uri"] == "https://embeddings.example.com/vectorize"
        assert web_api_skill["outputs"] == [{"name": "vector", "targetName": "content_vector"}]
        mapping = skillset_payload["indexProjections"]["selectors"][0]["mappings"][1]
        assert mapping["source"] == "/document/chunks/*/content_vector"

        indexer_payload = mock_put.call_args_list[2].args[2]
        assert indexer_payload["parameters"]["configuration"]["executionEnvironment"] == "private"

        mock_indexer_client.return_value.create_or_update_skillset.assert_not_called()
        mock_indexer_client.return_value.create_or_update_indexer.assert_not_called()

    def test_custom_web_api_multivector_requires_known_dimensions(self):
        from retrieve.indexing.advanced import create_multivector_index

        with pytest.raises(ValueError, match="custom_embedding_dimensions is required"):
            create_multivector_index(
                endpoint="https://test.search.windows.net",
                index_name="test-mv",
                ai_services_endpoint="https://test-ai.openai.azure.com",
                embedding_model="unknown-hf-model",
                custom_embedding_uri="https://embeddings.example.com/vectorize",
            )
