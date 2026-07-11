from __future__ import annotations

import json
import os
import uuid

from retrieve.graphrag_worker.app import IndexRequest, _jobs, _jobs_lock, _run_index


def _optional_int(name: str) -> int | None:
    value = os.environ.get(name, "").strip()
    return int(value) if value else None


def main() -> None:
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
        corpus_fingerprint=os.environ.get("CORPUS_FINGERPRINT", ""),
        ai_services_endpoint=os.environ.get("AI_SERVICES_ENDPOINT", ""),
        search_endpoint=os.environ.get("SEARCH_ENDPOINT", ""),
        llm_model=os.environ.get("LLM_DEPLOYMENT_NAME", "gpt-4.1"),
        embedding_model=os.environ.get("EMBEDDING_DEPLOYMENT_NAME", "text-embedding-3-large"),
        embedding_dimensions=_optional_int("EMBEDDING_DIMENSIONS") or 3_072,
    )
    _run_index(job_id, request)
    with _jobs_lock:
        status = dict(_jobs.get(job_id, {}))
    print(json.dumps(status, indent=2), flush=True)
    if status.get("state") != "succeeded":
        raise SystemExit(1)


if __name__ == "__main__":
    main()
