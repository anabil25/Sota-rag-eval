from __future__ import annotations

import asyncio
import json
import os
import uuid
from pathlib import Path

from retrieve.graphrag.query import execute_graphrag_query
from retrieve.graphrag_worker.app import (
    IndexRequest,
    QueryRequest,
    _blob_service,
    _load_remote_corpus_manifest,
    _load_successful_run_config,
    _run_index,
    _status_blob_name,
    collect_graphrag_model_metrics,
)
from retrieve.graphrag_worker.protocol import decode_payload, format_job_result
from retrieve.indexing.blob_upload import BlobMirrorPlan, upload_corpus
from retrieve.ingest.manifest import load_corpus_manifest


def _optional_int(name: str) -> int | None:
    value = os.environ.get(name, "").strip()
    return int(value) if value else None


def _required_document_ids() -> list[str]:
    encoded = os.environ.get("GRAPHRAG_SAMPLE_SELECTION", "").strip()
    if not encoded:
        return []
    payload = decode_payload(encoded)
    document_ids = payload.get("required_document_ids")
    if not isinstance(document_ids, list) or not all(
        isinstance(document_id, str) and document_id for document_id in document_ids
    ):
        raise ValueError("GraphRAG sample selection contains invalid document IDs")
    return document_ids


def seed_canonical_corpus() -> dict[str, object]:
    corpus_dir = Path(os.environ.get("BUNDLED_CORPUS_DIR", "/app/corpus"))
    storage_account = os.environ.get("STORAGE_ACCOUNT_NAME", "").strip()
    container = os.environ.get("CORPUS_CONTAINER_NAME", "corpus").strip()
    if not storage_account or not container:
        raise RuntimeError("Corpus seed requires Storage account and container names")

    manifest = load_corpus_manifest(corpus_dir)
    plan = upload_corpus(
        str(corpus_dir),
        storage_account,
        container,
        dry_run=True,
    )
    if not isinstance(plan, BlobMirrorPlan):
        raise RuntimeError("Corpus seed dry run did not return a mirror plan")
    if plan.corpus_fingerprint != manifest["corpus_fingerprint"]:
        raise RuntimeError("Corpus seed plan fingerprint does not match the bundled manifest")
    if plan.unmanaged:
        raise RuntimeError(
            "Corpus seed is blocked by unmanaged remote Markdown: " + ", ".join(plan.unmanaged[:5])
        )
    count = upload_corpus(
        str(corpus_dir),
        storage_account,
        container,
        expected_plan=plan,
    )
    if count != manifest["document_count"]:
        raise RuntimeError("Corpus seed count does not match the bundled manifest")
    return {
        "kind": "seed",
        "state": "succeeded",
        "document_count": count,
        "corpus_fingerprint": manifest["corpus_fingerprint"],
    }


def query_graphrag() -> dict[str, object]:
    envelope = decode_payload(os.environ.get("GRAPH_QUERY_PAYLOAD", ""))
    request_id = str(envelope.get("request_id", ""))
    if not request_id:
        raise RuntimeError("GraphRAG query payload requires a request ID")
    request = QueryRequest.model_validate(envelope.get("query"))
    storage_account = os.environ.get("STORAGE_ACCOUNT_NAME", "").strip()
    output_container = os.environ.get("GRAPH_OUTPUT_CONTAINER", "graphrag").strip()
    corpus_container = os.environ.get("CORPUS_CONTAINER_NAME", "corpus").strip()
    if not storage_account or not output_container or not corpus_container:
        raise RuntimeError("GraphRAG query storage is not configured")

    config = _load_successful_run_config(
        storage_account,
        output_container,
        request.artifact_prefix,
        request.corpus_fingerprint,
    )
    manifest = _load_remote_corpus_manifest(storage_account, corpus_container)
    if manifest.get("corpus_fingerprint") != request.corpus_fingerprint:
        raise RuntimeError("Canonical corpus fingerprint no longer matches the query run")
    result = asyncio.run(
        execute_graphrag_query(
            config=config,
            corpus_manifest=manifest,
            query=request.query,
            mode=request.mode,
            response_type=request.response_type,
            community_level=request.community_level,
            dynamic_community_selection=request.dynamic_community_selection,
        )
    )
    return {
        "kind": "query",
        "request_id": request_id,
        "answer": result.answer,
        "mode": result.mode,
        "text_unit_ids": list(result.text_unit_ids),
        "document_ids": list(result.document_ids),
        "model_metrics": collect_graphrag_model_metrics(config),
        "citations": [
            {
                "text_unit_id": citation.text_unit_id,
                "document_id": citation.document_id,
                "relative_path": citation.relative_path,
                "source_url": citation.source_url,
            }
            for citation in result.citations
        ],
        "latency_ms": result.latency_ms,
    }


def query_graphrag_batch() -> dict[str, object]:
    """Run an evaluation query batch against one loaded immutable graph."""
    envelope = decode_payload(os.environ.get("GRAPH_QUERY_PAYLOAD", ""))
    request_id = str(envelope.get("request_id", ""))
    if not request_id:
        raise RuntimeError("GraphRAG query payload requires a request ID")
    raw_queries = envelope.get("queries")
    if not isinstance(raw_queries, list) or not raw_queries:
        raise RuntimeError("GraphRAG batch payload requires at least one query")
    requests = [QueryRequest.model_validate(raw_query) for raw_query in raw_queries]
    first = requests[0]
    if any(
        request.artifact_prefix != first.artifact_prefix
        or request.corpus_fingerprint != first.corpus_fingerprint
        for request in requests[1:]
    ):
        raise RuntimeError("GraphRAG batch queries must use one immutable graph run")

    storage_account = os.environ.get("STORAGE_ACCOUNT_NAME", "").strip()
    output_container = os.environ.get("GRAPH_OUTPUT_CONTAINER", "graphrag").strip()
    corpus_container = os.environ.get("CORPUS_CONTAINER_NAME", "corpus").strip()
    if not storage_account or not output_container or not corpus_container:
        raise RuntimeError("GraphRAG query storage is not configured")
    config = _load_successful_run_config(
        storage_account,
        output_container,
        first.artifact_prefix,
        first.corpus_fingerprint,
    )
    manifest = _load_remote_corpus_manifest(storage_account, corpus_container)
    if manifest.get("corpus_fingerprint") != first.corpus_fingerprint:
        raise RuntimeError("Canonical corpus fingerprint no longer matches the query run")

    async def execute_batch() -> list[dict[str, object]]:
        results: list[dict[str, object]] = []
        for request in requests:
            result = await execute_graphrag_query(
                config=config,
                corpus_manifest=manifest,
                query=request.query,
                mode=request.mode,
                response_type=request.response_type,
                community_level=request.community_level,
                dynamic_community_selection=request.dynamic_community_selection,
            )
            results.append(
                {
                    "document_ids": list(result.document_ids),
                    "latency_ms": result.latency_ms,
                }
            )
        return results

    return {
        "kind": "query-batch",
        "request_id": request_id,
        "results": asyncio.run(execute_batch()),
        "model_metrics": collect_graphrag_model_metrics(config),
    }


def _load_durable_status(job_id: str) -> dict[str, object]:
    storage_account = os.environ.get("STORAGE_ACCOUNT_NAME", "").strip()
    output_container = os.environ.get("GRAPH_OUTPUT_CONTAINER", "graphrag").strip()
    if not storage_account or not output_container:
        raise RuntimeError("GraphRAG durable status storage is not configured")
    payload = (
        _blob_service(storage_account)
        .get_container_client(output_container)
        .download_blob(_status_blob_name(job_id))
        .readall()
    )
    status = json.loads(bytes(payload).decode("utf-8"))
    if not isinstance(status, dict) or status.get("job_id") != job_id:
        raise RuntimeError("GraphRAG durable status is invalid")
    return status


def main() -> None:
    mode = os.environ.get("GRAPH_WORKER_MODE", "index").strip().lower()
    if mode == "seed":
        print(format_job_result(seed_canonical_corpus()), flush=True)
        return
    if mode == "query":
        envelope = decode_payload(os.environ.get("GRAPH_QUERY_PAYLOAD", ""))
        result = query_graphrag_batch() if "queries" in envelope else query_graphrag()
        print(format_job_result(result), flush=True)
        return
    if mode != "index":
        raise RuntimeError(f"Unsupported GraphRAG worker mode: {mode}")

    job_id = os.environ.get("GRAPH_WORKER_JOB_ID") or uuid.uuid4().hex
    request = IndexRequest(
        storage_account=os.environ.get("STORAGE_ACCOUNT_NAME", ""),
        corpus_container=os.environ.get("CORPUS_CONTAINER_NAME", "corpus"),
        corpus_prefix=os.environ.get("CORPUS_PREFIX", ""),
        output_container=os.environ.get("GRAPH_OUTPUT_CONTAINER", "graphrag"),
        output_prefix=os.environ.get("GRAPH_OUTPUT_PREFIX", ""),
        method=os.environ.get("GRAPHRAG_METHOD", "fast"),
        run_scope=os.environ.get("GRAPHRAG_RUN_SCOPE", "full"),
        max_documents=_optional_int("GRAPHRAG_MAX_DOCUMENTS"),
        chunk_size=_optional_int("GRAPHRAG_CHUNK_SIZE"),
        chunk_overlap=_optional_int("GRAPHRAG_CHUNK_OVERLAP"),
        required_document_ids=_required_document_ids(),
        corpus_fingerprint=os.environ.get("CORPUS_FINGERPRINT", ""),
        ai_services_endpoint=os.environ.get("AI_SERVICES_ENDPOINT", ""),
        search_endpoint=os.environ.get("SEARCH_ENDPOINT", ""),
        llm_model=os.environ.get("LLM_DEPLOYMENT_NAME", "gpt-4.1"),
        embedding_model=os.environ.get("EMBEDDING_DEPLOYMENT_NAME", "text-embedding-3-large"),
        embedding_dimensions=_optional_int("EMBEDDING_DIMENSIONS") or 3_072,
    )
    _run_index(job_id, request)
    durable_status = _load_durable_status(job_id)
    print(
        format_job_result({"kind": "index", "status": durable_status}),
        flush=True,
    )
    if durable_status.get("state") != "succeeded":
        raise SystemExit(1)


if __name__ == "__main__":
    main()
