from __future__ import annotations

from types import SimpleNamespace
from unittest.mock import AsyncMock, patch

import pytest

from retrieve.ingest.manifest import build_manifest_entry, write_corpus_manifest
from retrieve.ingest.plugin import ConvertedDoc
from retrieve.ingest.run import save_doc


def _corpus(tmp_path):
    document = ConvertedDoc(
        "100-3",
        "Confidentiality",
        "",
        "https://example.test/100-3.htm",
        "Confidential information is protected.",
    )
    output = save_doc(document, tmp_path)
    write_corpus_manifest(
        tmp_path,
        [build_manifest_entry(document, output, tmp_path)],
    )


@patch("retrieve.indexing.advanced._create_lightrag")
def test_local_index_uses_stable_ids_and_storage_lifecycle(mock_create, tmp_path):
    from retrieve.indexing.advanced import run_lightrag_indexing

    _corpus(tmp_path)
    rag = SimpleNamespace(
        initialize_storages=AsyncMock(),
        ainsert=AsyncMock(return_value="track-1"),
        finalize_storages=AsyncMock(),
    )
    mock_create.return_value = rag

    run_lightrag_indexing(
        str(tmp_path),
        "https://test-ai.cognitiveservices.azure.com/",
    )

    rag.initialize_storages.assert_awaited_once()
    rag.ainsert.assert_awaited_once()
    assert rag.ainsert.await_args.kwargs["ids"] == "100-3"
    assert rag.ainsert.await_args.kwargs["file_paths"].endswith("100-3_confidentiality.md")
    rag.finalize_storages.assert_awaited_once()


@patch("retrieve.indexing.advanced._create_lightrag")
def test_local_index_fails_if_any_document_fails(mock_create, tmp_path):
    from retrieve.indexing.advanced import run_lightrag_indexing

    _corpus(tmp_path)
    mock_create.return_value = SimpleNamespace(
        initialize_storages=AsyncMock(),
        ainsert=AsyncMock(side_effect=RuntimeError("model failure")),
        finalize_storages=AsyncMock(),
    )

    with pytest.raises(RuntimeError, match="failed to index 1 document"):
        run_lightrag_indexing(
            str(tmp_path),
            "https://test-ai.cognitiveservices.azure.com/",
        )


@patch("retrieve.indexing.advanced._create_lightrag")
def test_local_query_returns_manifest_document_ids(mock_create, tmp_path):
    from retrieve.indexing.advanced import query_lightrag

    _corpus(tmp_path)
    rag = SimpleNamespace(
        initialize_storages=AsyncMock(),
        aquery_data=AsyncMock(
            return_value={
                "status": "success",
                "data": {
                    "chunks": [
                        {
                            "chunk_id": "chunk-1",
                            "file_path": "100/100-3_confidentiality.md",
                        }
                    ]
                },
            }
        ),
        finalize_storages=AsyncMock(),
    )
    mock_create.return_value = rag

    document_ids, latency_ms = query_lightrag(
        "What is confidential?",
        corpus_dir=str(tmp_path),
        ai_services_endpoint="https://test-ai.cognitiveservices.azure.com/",
    )

    assert document_ids == ["100-3"]
    assert latency_ms >= 0
    rag.aquery_data.assert_awaited_once()
    rag.finalize_storages.assert_awaited_once()


@pytest.mark.asyncio
async def test_lightrag_completion_passes_entra_provider_to_client_config(tmp_path):
    from retrieve.indexing.advanced import _create_lightrag

    captured = {}

    class FakeLightRAG:
        def __init__(self, **kwargs):
            captured.update(kwargs)

    complete = AsyncMock(return_value="answer")
    token_provider = object()
    with (
        patch(
            "lightrag.llm.openai.azure_openai_complete_if_cache",
            complete,
        ),
        patch("retrieve.indexing.advanced.DefaultAzureCredential"),
        patch(
            "retrieve.indexing.advanced.get_bearer_token_provider",
            return_value=token_provider,
        ),
    ):
        _create_lightrag(
            FakeLightRAG,
            working_dir=str(tmp_path),
            ai_services_endpoint="https://test-ai.cognitiveservices.azure.com/",
            llm_model="gpt-4.1",
            embedding_model="text-embedding-3-large",
        )

    await captured["llm_model_func"]("prompt")

    assert complete.await_args.kwargs["openai_client_configs"] == {
        "azure_ad_token_provider": token_provider
    }
    assert "client_configs" not in complete.await_args.kwargs
