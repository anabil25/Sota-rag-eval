"""Tests for structured GraphRAG public-query evidence mapping."""

from types import SimpleNamespace
from unittest.mock import AsyncMock, MagicMock, patch

import pandas as pd
import pytest

from retrieve.graphrag.query import (
    build_graphrag_evidence,
    execute_graphrag_query,
)


def _manifest(graph_document_id: str = "a" * 128) -> dict:
    return {
        "schema_version": 1,
        "status": "complete",
        "corpus_fingerprint": "f" * 64,
        "document_count": 1,
        "documents": [
            {
                "document_id": "100-3",
                "graphrag_document_id": graph_document_id,
                "source_id": "sha256:" + "b" * 64,
                "source_url": "https://example.test/100-3.htm",
                "relative_path": "100/100-3_confidentiality.md",
                "content_sha256": "c" * 64,
                "file_sha256": "d" * 64,
            }
        ],
    }


def _tables(graph_document_id: str = "a" * 128) -> dict:
    return {
        "text_units": pd.DataFrame(
            [
                {
                    "id": "text-unit-1",
                    "human_readable_id": 7,
                    "text": "Confidential case information is protected.",
                    "document_id": graph_document_id,
                }
            ]
        ),
        "entities": pd.DataFrame(
            [
                {
                    "id": "entity-1",
                    "human_readable_id": 4,
                    "text_unit_ids": ["text-unit-1"],
                }
            ]
        ),
        "relationships": pd.DataFrame(
            [
                {
                    "id": "relationship-1",
                    "human_readable_id": 9,
                    "text_unit_ids": ["text-unit-1"],
                }
            ]
        ),
        "community_reports": pd.DataFrame(
            [{"id": "report-1", "community": 3, "human_readable_id": 3}]
        ),
        "communities": pd.DataFrame(
            [{"id": "community-1", "community": 3, "text_unit_ids": ["text-unit-1"]}]
        ),
        "covariates": None,
    }


def test_source_context_maps_to_canonical_document():
    context = {"sources": pd.DataFrame([{"id": "7", "text": "protected"}])}

    text_units, document_ids, citations = build_graphrag_evidence(
        context,
        _tables(),
        _manifest(),
    )

    assert text_units == ("text-unit-1",)
    assert document_ids == ("100-3",)
    assert citations[0].document_id == "100-3"
    assert citations[0].relative_path == "100/100-3_confidentiality.md"
    assert citations[0].source_url == "https://example.test/100-3.htm"


def test_report_context_maps_through_community_text_units():
    context = {"reports": pd.DataFrame([{"id": "3", "title": "Confidentiality"}])}

    text_units, document_ids, citations = build_graphrag_evidence(
        context,
        _tables(),
        _manifest(),
    )

    assert text_units == ("text-unit-1",)
    assert document_ids == ("100-3",)
    assert len(citations) == 1


def test_direct_sources_take_precedence_over_indirect_graph_context():
    tables = _tables()
    tables["text_units"] = pd.concat(
        [
            tables["text_units"],
            pd.DataFrame(
                [
                    {
                        "id": "text-unit-2",
                        "human_readable_id": 8,
                        "text": "Indirect community context.",
                        "document_id": "b" * 128,
                    }
                ]
            ),
        ],
        ignore_index=True,
    )
    tables["communities"].loc[0, "text_unit_ids"] = ["text-unit-2"]
    manifest = _manifest()
    manifest["documents"].append(
        {
            "document_id": "indirect-doc",
            "graphrag_document_id": "b" * 128,
            "source_id": "sha256:" + "e" * 64,
            "source_url": "https://example.test/indirect.htm",
            "relative_path": "indirect.md",
            "content_sha256": "f" * 64,
            "file_sha256": "0" * 64,
        }
    )
    context = {
        "sources": pd.DataFrame([{"id": "7", "text": "direct"}]),
        "reports": pd.DataFrame([{"id": "3", "title": "indirect"}]),
    }

    text_units, document_ids, _ = build_graphrag_evidence(context, tables, manifest)

    assert text_units == ("text-unit-1",)
    assert document_ids == ("100-3",)


def test_unmapped_graphrag_document_id_is_rejected():
    context = {"sources": pd.DataFrame([{"id": "7", "text": "protected"}])}

    with pytest.raises(RuntimeError, match="absent from the canonical corpus manifest"):
        build_graphrag_evidence(
            context,
            _tables(graph_document_id="e" * 128),
            _manifest(),
        )


@pytest.mark.asyncio
async def test_execute_local_query_returns_answer_and_structured_context(monkeypatch):
    import graphrag.api

    import retrieve.graphrag.query as query_module

    tables = _tables()
    monkeypatch.setattr(
        query_module,
        "_load_query_tables",
        AsyncMock(return_value=tables),
    )
    local_search = AsyncMock(
        return_value=(
            "Protected information may be disclosed only under the policy.",
            {"sources": pd.DataFrame([{"id": "7", "text": "protected"}])},
        )
    )
    monkeypatch.setattr(graphrag.api, "local_search", local_search)

    result = await execute_graphrag_query(
        config=SimpleNamespace(),
        corpus_manifest=_manifest(),
        query="When may information be disclosed?",
        mode="local",
    )

    assert result.answer.startswith("Protected information")
    assert result.document_ids == ("100-3",)
    assert result.text_unit_ids == ("text-unit-1",)
    assert result.context["sources"][0]["id"] == "7"
    assert result.latency_ms >= 0
    local_search.assert_awaited_once()


@patch("retrieve.indexing.advanced.requests.post")
def test_remote_query_returns_only_structured_document_ids(mock_post):
    from retrieve.indexing.advanced import query_graphrag

    response = MagicMock()
    response.json.return_value = {
        "answer": "Answer",
        "document_ids": ["100-3", "101"],
        "citations": [{"text_unit_id": "tu-1", "document_id": "100-3"}],
    }
    mock_post.return_value = response

    document_ids, latency_ms = query_graphrag(
        query="What is confidential?",
        mode="local",
        graph_worker_endpoint="https://worker.internal",
        artifact_prefix=f"runs/{'f' * 64}/job123",
        corpus_fingerprint="f" * 64,
    )

    assert document_ids == ["100-3", "101"]
    assert latency_ms >= 0
    payload = mock_post.call_args.kwargs["json"]
    assert payload["artifact_prefix"] == f"runs/{'f' * 64}/job123"
    assert payload["corpus_fingerprint"] == "f" * 64


@patch("retrieve.indexing.advanced.execute_graphrag_query")
@patch("retrieve.indexing.advanced.load_successful_graphrag_run_config")
def test_localhost_query_reads_successful_blob_run(mock_load_config, mock_query, tmp_path):
    from types import SimpleNamespace
    from unittest.mock import AsyncMock

    from retrieve.indexing.advanced import query_graphrag
    from retrieve.ingest.manifest import build_manifest_entry, write_corpus_manifest
    from retrieve.ingest.plugin import ConvertedDoc
    from retrieve.ingest.run import save_doc

    doc = ConvertedDoc(
        "100-3",
        "Confidentiality",
        "",
        "https://example.test/100-3.htm",
        "Confidential information is protected.",
    )
    output = save_doc(doc, tmp_path)
    manifest = write_corpus_manifest(
        tmp_path,
        [build_manifest_entry(doc, output, tmp_path)],
    )
    fingerprint = manifest["corpus_fingerprint"]
    mock_load_config.return_value = object()
    mock_query.side_effect = AsyncMock(return_value=SimpleNamespace(document_ids=("100-3",)))

    document_ids, latency_ms = query_graphrag(
        query="What is confidential?",
        corpus_dir=str(tmp_path),
        storage_account="teststore",
        output_container="graphrag",
        search_endpoint="https://test.search.windows.net",
        artifact_prefix=f"runs/{fingerprint}/job123",
        corpus_fingerprint=fingerprint,
    )

    assert document_ids == ["100-3"]
    assert latency_ms >= 0
    mock_load_config.assert_called_once_with(
        storage_account="teststore",
        output_container="graphrag",
        artifact_prefix=f"runs/{fingerprint}/job123",
        corpus_fingerprint=fingerprint,
        search_endpoint="https://test.search.windows.net",
    )
    mock_query.assert_awaited_once()


@patch("retrieve.indexing.advanced.get_container_job_logs")
@patch("retrieve.indexing.advanced.wait_for_container_job")
@patch("retrieve.indexing.advanced.start_container_job")
@patch("retrieve.indexing.advanced.uuid.uuid4")
def test_localhost_query_uses_private_container_job(
    mock_uuid,
    mock_start,
    mock_wait,
    mock_logs,
):
    from types import SimpleNamespace

    from retrieve.graphrag_worker.protocol import decode_payload, format_job_result
    from retrieve.indexing.advanced import query_graphrag

    fingerprint = "f" * 64
    mock_uuid.return_value = SimpleNamespace(hex="request123")
    mock_start.return_value = "execution-123"
    mock_logs.return_value = format_job_result(
        {
            "kind": "query",
            "request_id": "request123",
            "document_ids": ["100-3", "101"],
            "latency_ms": 12.5,
            "model_metrics": {
                "azure/gpt-4.1": {
                    "attempted_request_count": 1,
                    "total_tokens": 42,
                }
            },
        }
    )
    captured_metrics = {}

    document_ids, latency_ms = query_graphrag(
        query="What is confidential?",
        mode="local",
        graph_job_name="azgrjtest",
        resource_group="rg-test",
        subscription_id="sub-test",
        artifact_prefix=f"runs/{fingerprint}/job123",
        corpus_fingerprint=fingerprint,
        metrics_sink=captured_metrics.update,
    )

    assert document_ids == ["100-3", "101"]
    assert latency_ms >= 0
    environment = mock_start.call_args.kwargs["environment"]
    assert environment[0] == "GRAPH_WORKER_MODE=query"
    payload = decode_payload(environment[1].split("=", 1)[1])
    assert payload["request_id"] == "request123"
    assert payload["query"]["artifact_prefix"] == f"runs/{fingerprint}/job123"
    assert captured_metrics["azure/gpt-4.1"]["total_tokens"] == 42
    mock_wait.assert_called_once()


def test_worker_query_returns_compact_structured_evidence(monkeypatch):
    from types import SimpleNamespace
    from unittest.mock import AsyncMock

    from retrieve.graphrag.query import GraphRagCitation
    from retrieve.graphrag_worker import run_job
    from retrieve.graphrag_worker.protocol import encode_payload

    fingerprint = "f" * 64
    monkeypatch.setenv("STORAGE_ACCOUNT_NAME", "teststore")
    monkeypatch.setenv("GRAPH_OUTPUT_CONTAINER", "graphrag")
    monkeypatch.setenv("CORPUS_CONTAINER_NAME", "corpus")
    monkeypatch.setenv(
        "GRAPH_QUERY_PAYLOAD",
        encode_payload(
            {
                "request_id": "request123",
                "query": {
                    "artifact_prefix": f"runs/{fingerprint}/job123",
                    "corpus_fingerprint": fingerprint,
                    "query": "What is confidential?",
                    "mode": "local",
                },
            }
        ),
    )
    monkeypatch.setattr(run_job, "_load_successful_run_config", lambda *args: object())
    monkeypatch.setattr(
        run_job,
        "_load_remote_corpus_manifest",
        lambda *args: {"corpus_fingerprint": fingerprint, "documents": []},
    )
    execute = AsyncMock(
        return_value=SimpleNamespace(
            answer="Confidential information is protected.",
            mode="local",
            text_unit_ids=("tu-1",),
            document_ids=("100-3",),
            citations=(
                GraphRagCitation(
                    text_unit_id="tu-1",
                    document_id="100-3",
                    graphrag_document_id="a" * 128,
                    relative_path="100/100-3.md",
                    source_url="https://example.test/100-3.htm",
                    text="Confidential information is protected.",
                ),
            ),
            latency_ms=12.5,
        )
    )
    monkeypatch.setattr(run_job, "execute_graphrag_query", execute)
    monkeypatch.setattr(
        run_job,
        "collect_graphrag_model_metrics",
        lambda _config: {"azure/gpt-4.1": {"attempted_request_count": 1}},
    )

    result = run_job.query_graphrag()

    assert result["kind"] == "query"
    assert result["request_id"] == "request123"
    assert result["document_ids"] == ["100-3"]
    assert result["model_metrics"] == {
        "azure/gpt-4.1": {"attempted_request_count": 1}
    }
    assert result["citations"][0]["text_unit_id"] == "tu-1"
    assert "text" not in result["citations"][0]
    execute.assert_awaited_once()


@pytest.mark.asyncio
async def test_internal_query_endpoint_is_default_off(monkeypatch):
    from fastapi import HTTPException

    from retrieve.graphrag_worker.app import QueryRequest, query_index

    monkeypatch.delenv("RETRIEVE_GRAPH_QUERY_ENABLED", raising=False)

    with pytest.raises(HTTPException) as exc_info:
        await query_index(
            QueryRequest(
                artifact_prefix=f"runs/{'f' * 64}/job123",
                corpus_fingerprint="f" * 64,
                query="What is confidential?",
            )
        )

    assert exc_info.value.status_code == 404


@pytest.mark.asyncio
async def test_internal_query_endpoint_returns_structured_result(monkeypatch):
    import retrieve.graphrag_worker.app as worker
    from retrieve.graphrag.query import GraphRagCitation, GraphRagQueryResult

    fingerprint = "f" * 64
    result = GraphRagQueryResult(
        answer="Confidential information is protected.",
        mode="local",
        text_unit_ids=("tu-1",),
        document_ids=("100-3",),
        citations=(
            GraphRagCitation(
                text_unit_id="tu-1",
                document_id="100-3",
                graphrag_document_id="a" * 128,
                relative_path="100/100-3.md",
                source_url="https://example.test/100-3.htm",
                text="Confidential information is protected.",
            ),
        ),
        context={"sources": [{"id": "1"}]},
        latency_ms=12.5,
    )
    monkeypatch.setenv("RETRIEVE_GRAPH_QUERY_ENABLED", "true")
    monkeypatch.setenv("STORAGE_ACCOUNT_NAME", "teststore")
    monkeypatch.setenv("GRAPH_OUTPUT_CONTAINER", "graphrag")
    monkeypatch.setenv("CORPUS_CONTAINER_NAME", "corpus")
    monkeypatch.setattr(worker, "_load_successful_run_config", lambda *args: object())
    monkeypatch.setattr(
        worker,
        "_load_remote_corpus_manifest",
        lambda *args: {"corpus_fingerprint": fingerprint, "documents": []},
    )
    execute = AsyncMock(return_value=result)
    monkeypatch.setattr(worker, "execute_graphrag_query", execute)
    monkeypatch.setattr(
        worker,
        "collect_graphrag_model_metrics",
        lambda _config: {"azure/gpt-4.1": {"attempted_request_count": 1}},
    )

    response = await worker.query_index(
        worker.QueryRequest(
            artifact_prefix=f"runs/{fingerprint}/job123",
            corpus_fingerprint=fingerprint,
            query="What is confidential?",
        )
    )

    assert response["answer"].startswith("Confidential")
    assert response["document_ids"] == ["100-3"]
    assert response["model_metrics"] == {
        "azure/gpt-4.1": {"attempted_request_count": 1}
    }
    assert response["citations"][0]["text_unit_id"] == "tu-1"
    execute.assert_awaited_once()


@patch("retrieve.graphrag_worker.app._blob_service")
def test_successful_run_config_is_boundary_validated(
    mock_blob_service,
    monkeypatch,
):
    import json

    import yaml

    from retrieve.graphrag.settings import build_graphrag_settings
    from retrieve.graphrag_worker.app import _load_successful_run_config

    fingerprint = "f" * 64
    prefix = f"runs/{fingerprint}/job123"
    settings = build_graphrag_settings(
        input_dir="input",
        ai_services_endpoint="https://test-ai.cognitiveservices.azure.com/",
        storage_account_blob_url="https://teststore.blob.core.windows.net",
        storage_container="graphrag",
        run_prefix=prefix,
        cache_prefix=f"cache/{fingerprint}",
        search_endpoint="https://test.search.windows.net",
        vector_index_prefix="gr-ffffffff-job123",
    )
    status = {
        "job_id": "job123",
        "state": "succeeded",
        "artifact_prefix": prefix,
    }
    blobs = {
        "jobs/job123/status.json": json.dumps(status).encode("utf-8"),
        f"{prefix}/settings.yaml": yaml.safe_dump(settings).encode("utf-8"),
    }
    container = mock_blob_service.return_value.get_container_client.return_value
    container.download_blob.side_effect = lambda name: SimpleNamespace(readall=lambda: blobs[name])
    monkeypatch.setenv("SEARCH_ENDPOINT", "https://test.search.windows.net")

    config = _load_successful_run_config(
        "teststore",
        "graphrag",
        prefix,
        fingerprint,
    )

    assert config.output_storage.base_dir == f"{prefix}/output"
    assert config.vector_store.url == "https://test.search.windows.net"

    status["state"] = "running"
    blobs["jobs/job123/status.json"] = json.dumps(status).encode("utf-8")
    with pytest.raises(ValueError, match="successful immutable run"):
        _load_successful_run_config(
            "teststore",
            "graphrag",
            prefix,
            fingerprint,
        )
