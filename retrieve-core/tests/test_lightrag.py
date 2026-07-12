from __future__ import annotations

from pathlib import Path
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
        working_dir=str(tmp_path / "state"),
    )

    rag.initialize_storages.assert_awaited_once()
    rag.ainsert.assert_awaited_once()
    assert rag.ainsert.await_args.kwargs["ids"] == ["100-3"]
    assert rag.ainsert.await_args.kwargs["file_paths"][0].endswith("100-3_confidentiality.md")
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

    with pytest.raises(RuntimeError, match="model failure"):
        run_lightrag_indexing(
            str(tmp_path),
            "https://test-ai.cognitiveservices.azure.com/",
            working_dir=str(tmp_path / "state"),
        )


@patch("retrieve.indexing.advanced._create_lightrag")
def test_local_index_includes_required_documents_outside_first_rows(mock_create, tmp_path):
    from retrieve.indexing.advanced import run_lightrag_indexing

    entries = []
    for index in range(10):
        document = ConvertedDoc(
            f"doc-{index}",
            f"Document {index}",
            "",
            f"https://example.test/{index}",
            f"Content {index}",
        )
        output = save_doc(document, tmp_path)
        entries.append(build_manifest_entry(document, output, tmp_path))
    write_corpus_manifest(tmp_path, entries)
    rag = SimpleNamespace(
        initialize_storages=AsyncMock(),
        ainsert=AsyncMock(return_value="track-1"),
        finalize_storages=AsyncMock(),
    )
    mock_create.return_value = rag

    result = run_lightrag_indexing(
        str(tmp_path),
        "https://test-ai.cognitiveservices.azure.com/",
        working_dir=str(tmp_path / "state"),
        max_documents=4,
        required_document_ids=["doc-9"],
    )

    inserted_ids = rag.ainsert.await_args.kwargs["ids"]
    assert len(inserted_ids) == 4
    assert "doc-9" in inserted_ids
    assert result["lightrag_required_document_ids"] == ["doc-9"]
    assert "doc-9" in result["lightrag_selected_document_ids"]
    assert result["lightrag_sample_selection"] == "required-plus-stratified"
    assert result["lightrag_working_dir"].startswith((tmp_path / "state" / "runs").as_posix())
    assert (tmp_path / "state" / "runs" / result["lightrag_index_fingerprint"]).is_dir()


@patch("retrieve.indexing.advanced._create_lightrag")
def test_local_index_failure_preserves_resumable_staging(mock_create, tmp_path):
    from retrieve.indexing.advanced import run_lightrag_indexing

    _corpus(tmp_path)
    state = tmp_path / "state"
    existing = state / "existing.txt"
    state.mkdir()
    existing.write_text("previous index", encoding="utf-8")
    mock_create.return_value = SimpleNamespace(
        initialize_storages=AsyncMock(),
        ainsert=AsyncMock(side_effect=RuntimeError("model failure")),
        finalize_storages=AsyncMock(),
    )

    with pytest.raises(RuntimeError, match="model failure"):
        run_lightrag_indexing(
            str(tmp_path),
            "https://test-ai.cognitiveservices.azure.com/",
            working_dir=str(state),
        )

    assert existing.read_text(encoding="utf-8") == "previous index"
    staging_directories = list((state / ".staging").iterdir())
    assert len(staging_directories) == 1
    staging = staging_directories[0]
    assert (staging / "retrieve-staging.json").is_file()
    assert not (staging / "retrieve-index.json").exists()

    successful_rag = SimpleNamespace(
        initialize_storages=AsyncMock(),
        ainsert=AsyncMock(return_value="track-2"),
        finalize_storages=AsyncMock(),
    )
    mock_create.return_value = successful_rag
    result = run_lightrag_indexing(
        str(tmp_path),
        "https://test-ai.cognitiveservices.azure.com/",
        working_dir=str(state),
    )

    assert successful_rag.ainsert.await_count == 1
    assert Path(result["lightrag_working_dir"]).is_dir()
    assert not staging.exists()


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
    query_param = rag.aquery_data.await_args.kwargs["param"]
    assert query_param.mode == "mix"
    assert query_param.top_k == 40
    assert query_param.chunk_top_k == 20
    assert query_param.enable_rerank is True
    assert query_param.include_references is True
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

    assert captured["max_parallel_insert"] == 1
    assert complete.await_args.kwargs["openai_client_configs"] == {
        "azure_ad_token_provider": token_provider
    }
    assert "client_configs" not in complete.await_args.kwargs
