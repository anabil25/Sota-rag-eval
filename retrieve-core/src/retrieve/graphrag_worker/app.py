from __future__ import annotations

import asyncio
import json
import logging
import os
import shutil
import threading
import time
import traceback
import uuid
from datetime import UTC, datetime
from pathlib import Path
from typing import Any

import yaml
from azure.identity import DefaultAzureCredential
from azure.storage.blob import BlobServiceClient, ContentSettings
from fastapi import BackgroundTasks, FastAPI, HTTPException
from pydantic import BaseModel, Field

from retrieve.graphrag.query import (
    GraphRagQueryMode,
    execute_graphrag_query,
    load_successful_graphrag_run_config,
)
from retrieve.graphrag.safety import (
    GraphRagRunScope,
    validate_graphrag_artifact_prefix,
    validate_graphrag_run_scope,
)
from retrieve.graphrag.settings import (
    DEFAULT_CONCURRENT_REQUESTS,
    DEFAULT_EMBEDDING_RPM,
    DEFAULT_EMBEDDING_TPM,
    DEFAULT_LLM_RPM,
    DEFAULT_LLM_TPM,
    DEFAULT_RETRY_BASE_DELAY_SECONDS,
    DEFAULT_RETRY_MAX_DELAY_SECONDS,
    DEFAULT_RETRY_MAX_RETRIES,
    build_graphrag_settings,
    validate_graphrag_settings,
)
from retrieve.ingest.manifest import MANIFEST_BLOB_NAME, validate_corpus_manifest_data

app = FastAPI(title="Retrieve GraphRAG Worker", version="0.1.0")
logging.basicConfig(level=os.environ.get("LOG_LEVEL", "INFO"))
log = logging.getLogger("retrieve.graphrag_worker")
logging.getLogger("azure.core.pipeline.policies.http_logging_policy").setLevel(logging.WARNING)

_jobs: dict[str, dict[str, Any]] = {}
_jobs_lock = threading.Lock()


def _now() -> str:
    return datetime.now(UTC).isoformat()


class IndexRequest(BaseModel):
    storage_account: str = Field(default="")
    corpus_container: str = Field(default="corpus")
    corpus_prefix: str = Field(default="")
    output_container: str = Field(default="graphrag")
    output_prefix: str = Field(default="")
    method: str = Field(default="fast")
    run_scope: GraphRagRunScope = Field(default="full")
    max_documents: int | None = Field(default=None, ge=1)
    corpus_fingerprint: str = Field(default="")
    ai_services_endpoint: str = Field(default="")
    search_endpoint: str = Field(default="")
    llm_model: str = Field(default="gpt-4.1")
    embedding_model: str = Field(default="text-embedding-3-large")
    embedding_dimensions: int = Field(default=3_072, ge=1)


class JobStatus(BaseModel):
    job_id: str
    state: str
    message: str = ""
    started_at: str
    updated_at: str
    artifact_prefix: str = ""
    corpus_fingerprint: str = ""
    run_scope: GraphRagRunScope = "full"
    max_documents: int | None = None
    error: str = ""
    heartbeat_at: str = ""
    workflows: list[str] = Field(default_factory=list)
    completed_workflows: list[str] = Field(default_factory=list)
    current_workflow: str = ""
    progress_description: str = ""
    progress_completed: int | None = None
    progress_total: int | None = None
    workflow_results: list[dict[str, str]] = Field(default_factory=list)


class QueryRequest(BaseModel):
    artifact_prefix: str
    corpus_fingerprint: str = Field(pattern=r"^[0-9a-f]{64}$")
    query: str = Field(min_length=1, max_length=8_000)
    mode: GraphRagQueryMode = "local"
    response_type: str = Field(default="Multiple Paragraphs", max_length=100)
    community_level: int = Field(default=2, ge=0, le=10)
    dynamic_community_selection: bool = False


def _credential() -> DefaultAzureCredential:
    return DefaultAzureCredential(exclude_interactive_browser_credential=True)


def _blob_service(storage_account: str) -> BlobServiceClient:
    return BlobServiceClient(
        account_url=f"https://{storage_account}.blob.core.windows.net",
        credential=_credential(),
    )


def _load_remote_corpus_manifest(
    storage_account: str,
    corpus_container: str,
) -> dict[str, Any]:
    container = _blob_service(storage_account).get_container_client(corpus_container)
    try:
        payload = container.download_blob(MANIFEST_BLOB_NAME).readall()
        manifest = json.loads(bytes(payload).decode("utf-8"))
    except Exception as exc:
        raise RuntimeError(
            f"Canonical corpus manifest is unavailable at {MANIFEST_BLOB_NAME}"
        ) from exc
    if not isinstance(manifest, dict):
        raise RuntimeError("Canonical corpus manifest must be a JSON object")
    try:
        validate_corpus_manifest_data(manifest)
    except ValueError as exc:
        raise RuntimeError(f"Canonical corpus manifest is invalid: {exc}") from exc
    return manifest


def _status_blob_name(job_id: str) -> str:
    return f"jobs/{job_id}/status.json"


def _truthy_env(name: str, default: str = "") -> bool:
    return os.environ.get(name, default).strip().lower() in {"1", "true", "yes"}


def _load_successful_run_config(
    storage_account: str,
    output_container: str,
    artifact_prefix: str,
    corpus_fingerprint: str,
) -> Any:
    return load_successful_graphrag_run_config(
        storage_account=storage_account,
        output_container=output_container,
        artifact_prefix=artifact_prefix,
        corpus_fingerprint=corpus_fingerprint,
        search_endpoint=os.environ.get("SEARCH_ENDPOINT", "").strip(),
        credential=_credential(),
    )


def _set_status(
    storage_account: str,
    output_container: str,
    status: dict[str, Any],
) -> None:
    status["updated_at"] = _now()
    with _jobs_lock:
        _jobs[status["job_id"]] = dict(status)

    try:
        blob_service = _blob_service(storage_account)
        container = blob_service.get_container_client(output_container)
    except Exception as exc:
        log.warning("Could not create Blob client for job status: %s", exc)
        return

    try:
        container.create_container()
    except Exception as exc:
        if "ContainerAlreadyExists" not in str(exc):
            log.warning("Could not create status container: %s", exc)

    try:
        container.upload_blob(
            _status_blob_name(status["job_id"]),
            json.dumps(status, indent=2).encode("utf-8"),
            overwrite=True,
            content_settings=ContentSettings(content_type="application/json"),
        )
    except Exception as exc:
        log.warning("Could not persist job status to Blob: %s", exc)


class RetrieveWorkflowCallbacks:
    """Persist GraphRAG workflow and item progress to the durable job status."""

    def __init__(
        self,
        storage_account: str,
        output_container: str,
        status: dict[str, Any],
        *,
        min_persist_interval: float = 2.0,
    ) -> None:
        self._storage_account = storage_account
        self._output_container = output_container
        self._status = status
        self._min_persist_interval = min_persist_interval
        self._last_persisted = 0.0
        self._lock = threading.Lock()

    def _persist(self, *, force: bool = False) -> None:
        with self._lock:
            now = time.monotonic()
            if not force and now - self._last_persisted < self._min_persist_interval:
                return
            self._status["heartbeat_at"] = _now()
            _set_status(
                self._storage_account,
                self._output_container,
                self._status,
            )
            self._last_persisted = now

    def pipeline_start(self, names: list[str]) -> None:
        self._status["workflows"] = list(names)
        self._status["completed_workflows"] = []
        self._status["message"] = "GraphRAG pipeline started"
        self._persist(force=True)

    def pipeline_end(self, results: list[Any]) -> None:
        self._status["current_workflow"] = ""
        self._status["message"] = "GraphRAG pipeline completed"
        self._status["workflow_results"] = [
            {
                "workflow": str(result.workflow),
                "error": str(result.error) if result.error else "",
            }
            for result in results
        ]
        self._persist(force=True)

    def workflow_start(self, name: str, instance: object) -> None:
        del instance
        self._status["current_workflow"] = name
        self._status["message"] = f"Running GraphRAG workflow: {name}"
        self._persist(force=True)

    def workflow_end(self, name: str, instance: object) -> None:
        del instance
        completed = self._status.setdefault("completed_workflows", [])
        if name not in completed:
            completed.append(name)
        self._status["current_workflow"] = ""
        self._status["message"] = f"Completed GraphRAG workflow: {name}"
        self._persist(force=True)

    def progress(self, progress: Any) -> None:
        self._status["progress_description"] = str(progress.description or "")
        self._status["progress_completed"] = progress.completed_items
        self._status["progress_total"] = progress.total_items
        if progress.description:
            self._status["message"] = str(progress.description)
        self._persist()

    def pipeline_error(self, error: BaseException) -> None:
        self._status["message"] = "GraphRAG pipeline error"
        self._status["error"] = str(error)
        self._persist(force=True)


def _download_corpus(
    storage_account: str,
    corpus_container: str,
    corpus_prefix: str,
    input_dir: Path,
    progress_status: dict[str, Any] | None = None,
    output_container: str = "graphrag",
    max_documents: int | None = None,
    managed_paths: list[str] | None = None,
) -> int:
    blob_service = _blob_service(storage_account)
    container = blob_service.get_container_client(corpus_container)
    count = 0
    prefix = corpus_prefix.strip("/")
    prefix_with_slash = f"{prefix}/" if prefix else ""

    if managed_paths is None:
        candidates = []
        for blob in container.list_blobs(name_starts_with=prefix_with_slash):
            name = str(blob.name)
            if name.lower().endswith(".md"):
                relative = name[len(prefix_with_slash):] if prefix_with_slash else name
                candidates.append((name, relative))
    else:
        selected = sorted(managed_paths)
        if max_documents is not None:
            selected = selected[:max_documents]
        candidates = [
            (f"{prefix_with_slash}{relative}", relative)
            for relative in selected
        ]

    for name, relative in candidates:
        target = input_dir / relative
        target.parent.mkdir(parents=True, exist_ok=True)
        target.write_bytes(container.download_blob(name).readall())
        count += 1
        if managed_paths is None and max_documents is not None and count >= max_documents:
            break
        if progress_status is not None and count % 250 == 0:
            progress_status["message"] = f"Downloaded {count} Markdown files"
            _set_status(storage_account, output_container, progress_status)
    return count


def _write_settings(
    root: Path,
    input_dir: Path,
    request: IndexRequest,
    *,
    storage_account: str = "",
    artifact_prefix: str = "",
    corpus_fingerprint: str = "",
    job_id: str = "",
) -> Any:
    concurrent_requests = _env_int(
        "GRAPHRAG_CONCURRENT_REQUESTS",
        DEFAULT_CONCURRENT_REQUESTS,
    )
    legacy_retry_max_retries = _env_int(
        "GRAPHRAG_RETRY_MAX_ATTEMPTS", DEFAULT_RETRY_MAX_RETRIES
    )
    retry_max_retries = _env_int(
        "GRAPHRAG_RETRY_MAX_RETRIES", legacy_retry_max_retries
    )
    retry_base_delay = _env_float(
        "GRAPHRAG_RETRY_BASE_DELAY_SECONDS", DEFAULT_RETRY_BASE_DELAY_SECONDS
    )
    legacy_retry_max_delay = _env_float(
        "GRAPHRAG_RETRY_MAX_WAIT_SECONDS", DEFAULT_RETRY_MAX_DELAY_SECONDS
    )
    retry_max_delay = _env_float(
        "GRAPHRAG_RETRY_MAX_DELAY_SECONDS", legacy_retry_max_delay
    )
    embedding_tpm = _env_int(
        "GRAPHRAG_EMBEDDING_TOKENS_PER_MINUTE",
        DEFAULT_EMBEDDING_TPM,
    )
    embedding_rpm = _env_int(
        "GRAPHRAG_EMBEDDING_REQUESTS_PER_MINUTE",
        DEFAULT_EMBEDDING_RPM,
    )
    llm_tpm = _env_int("GRAPHRAG_LLM_TOKENS_PER_MINUTE", DEFAULT_LLM_TPM)
    llm_rpm = _env_int("GRAPHRAG_LLM_REQUESTS_PER_MINUTE", DEFAULT_LLM_RPM)
    settings = build_graphrag_settings(
        input_dir=input_dir,
        ai_services_endpoint=request.ai_services_endpoint,
        llm_model=request.llm_model,
        embedding_model=request.embedding_model,
        method=request.method,
        concurrent_requests=concurrent_requests,
        retry_max_retries=retry_max_retries,
        retry_base_delay_seconds=retry_base_delay,
        retry_max_delay_seconds=retry_max_delay,
        embedding_tokens_per_minute=embedding_tpm,
        embedding_requests_per_minute=embedding_rpm,
        llm_tokens_per_minute=llm_tpm,
        llm_requests_per_minute=llm_rpm,
        storage_account_blob_url=(
            f"https://{storage_account}.blob.core.windows.net" if storage_account else ""
        ),
        storage_container=request.output_container,
        run_prefix=artifact_prefix,
        cache_prefix=f"cache/{corpus_fingerprint}" if corpus_fingerprint else "",
        search_endpoint=request.search_endpoint,
        vector_index_prefix=(
            f"gr-{corpus_fingerprint[:8]}-{job_id[:8]}"
            if corpus_fingerprint and job_id
            else ""
        ),
        embedding_dimensions=request.embedding_dimensions,
    )
    config = validate_graphrag_settings(settings)
    (root / "settings.yaml").write_text(
        yaml.dump(settings, default_flow_style=False),
        encoding="utf-8",
    )
    return config


def _env_int(name: str, default: int) -> int:
    try:
        return int(os.environ.get(name, str(default)))
    except ValueError:
        return default


def _env_float(name: str, default: float) -> float:
    try:
        return float(os.environ.get(name, str(default)))
    except ValueError:
        return default


def _upload_artifacts(
    storage_account: str,
    output_container: str,
    job_id: str,
    artifact_prefix: str,
    root: Path,
) -> None:
    blob_service = _blob_service(storage_account)
    container = blob_service.get_container_client(output_container)
    try:
        container.create_container()
    except Exception:
        pass

    prefix = artifact_prefix.strip("/") or job_id
    for directory in ("output", "logs", "settings.yaml"):
        source = root / directory
        if not source.exists():
            continue
        if source.is_file():
            files = [source]
        else:
            files = [path for path in source.rglob("*") if path.is_file()]
        for path in files:
            relative = path.relative_to(root).as_posix()
            container.upload_blob(f"{prefix}/{relative}", path.read_bytes(), overwrite=True)


def _run_index(job_id: str, request: IndexRequest) -> None:
    log.info("Starting GraphRAG index job %s", job_id)
    validate_graphrag_run_scope(request.run_scope, request.max_documents)
    validate_graphrag_artifact_prefix(request.output_prefix)

    storage_account = request.storage_account or os.environ.get("STORAGE_ACCOUNT_NAME", "")
    if not storage_account:
        raise RuntimeError("storage_account is required")

    request.storage_account = storage_account
    request.ai_services_endpoint = request.ai_services_endpoint or os.environ.get(
        "AI_SERVICES_ENDPOINT", ""
    )
    request.search_endpoint = request.search_endpoint or os.environ.get("SEARCH_ENDPOINT", "")
    request.llm_model = request.llm_model or os.environ.get("LLM_DEPLOYMENT_NAME", "gpt-4.1")
    request.embedding_model = request.embedding_model or os.environ.get(
        "EMBEDDING_DEPLOYMENT_NAME", "text-embedding-3-large"
    )
    request.output_container = request.output_container or os.environ.get(
        "GRAPH_OUTPUT_CONTAINER", "graphrag"
    )

    artifact_prefix = request.output_prefix.strip("/") or f"runs/pending/{job_id}"
    status = {
        "job_id": job_id,
        "state": "running",
        "message": "Starting GraphRAG indexing",
        "started_at": _now(),
        "updated_at": _now(),
        "artifact_prefix": artifact_prefix,
        "run_scope": request.run_scope,
        "max_documents": request.max_documents,
        "error": "",
    }
    _set_status(storage_account, request.output_container, status)

    work_root = Path(os.environ.get("WORK_DIR", "/tmp/retrieve-graphrag")) / job_id
    if work_root.exists():
        shutil.rmtree(work_root)
    input_dir = work_root / "input"
    project_dir = work_root / "project"
    input_dir.mkdir(parents=True, exist_ok=True)
    project_dir.mkdir(parents=True, exist_ok=True)

    try:
        manifest = _load_remote_corpus_manifest(
            storage_account,
            request.corpus_container,
        )
        corpus_fingerprint = str(manifest["corpus_fingerprint"])
        if (
            request.corpus_fingerprint
            and request.corpus_fingerprint != corpus_fingerprint
        ):
            raise RuntimeError(
                "Requested corpus fingerprint does not match the canonical Blob manifest"
            )
        if not request.search_endpoint:
            raise RuntimeError(
                "search_endpoint is required for persistent GraphRAG vector indexes"
            )
        artifact_prefix = request.output_prefix.strip("/") or (
            f"runs/{corpus_fingerprint}/{job_id}"
        )
        validate_graphrag_artifact_prefix(artifact_prefix)
        status["artifact_prefix"] = artifact_prefix
        status["corpus_fingerprint"] = corpus_fingerprint
        status["message"] = "Verified canonical corpus manifest"
        _set_status(storage_account, request.output_container, status)

        managed_paths = [
            str(document["relative_path"]) for document in manifest["documents"]
        ]
        count = _download_corpus(
            storage_account,
            request.corpus_container,
            request.corpus_prefix,
            input_dir,
            progress_status=status,
            output_container=request.output_container,
            max_documents=request.max_documents,
            managed_paths=managed_paths,
        )
        expected_count = min(
            len(managed_paths),
            request.max_documents or len(managed_paths),
        )
        if count != expected_count:
            raise RuntimeError(
                f"Canonical corpus download mismatch: expected {expected_count}, got {count}"
            )
        status["message"] = f"Downloaded {count} Markdown files"
        _set_status(storage_account, request.output_container, status)

        config = _write_settings(
            project_dir,
            input_dir,
            request,
            storage_account=storage_account,
            artifact_prefix=artifact_prefix,
            corpus_fingerprint=corpus_fingerprint,
            job_id=job_id,
        )
        status["message"] = "Running GraphRAG index"
        _set_status(storage_account, request.output_container, status)
        from graphrag.api import build_index

        callbacks = RetrieveWorkflowCallbacks(
            storage_account,
            request.output_container,
            status,
        )
        results = asyncio.run(
            build_index(
                config=config,
                method=request.method,
                callbacks=[callbacks],
                additional_context={
                    "job_id": job_id,
                    "corpus_fingerprint": corpus_fingerprint,
                    "run_scope": request.run_scope,
                },
            )
        )
        failures = [result for result in results if result.error is not None]
        if failures:
            details = "; ".join(
                f"{result.workflow}: {result.error}" for result in failures
            )
            raise RuntimeError(f"GraphRAG workflows failed: {details}")

        _upload_artifacts(
            storage_account,
            request.output_container,
            job_id,
            artifact_prefix,
            project_dir,
        )
        status["state"] = "succeeded"
        status["message"] = "GraphRAG indexing complete"
        _set_status(storage_account, request.output_container, status)
        log.info("GraphRAG index job %s succeeded", job_id)
    except Exception as exc:
        status["state"] = "failed"
        status["message"] = "GraphRAG indexing failed"
        status["error"] = f"{exc}\n{traceback.format_exc()}"
        log.exception("GraphRAG index job %s failed", job_id)
        try:
            _upload_artifacts(
                storage_account,
                request.output_container,
                job_id,
                artifact_prefix,
                project_dir,
            )
        except Exception:
            pass
        _set_status(storage_account, request.output_container, status)


@app.get("/health")
def health() -> dict[str, str]:
    return {"status": "ok"}


@app.post("/query")
async def query_index(request: QueryRequest) -> dict[str, Any]:
    if not _truthy_env("RETRIEVE_GRAPH_QUERY_ENABLED"):
        raise HTTPException(status_code=404, detail="Not found")

    storage_account = os.environ.get("STORAGE_ACCOUNT_NAME", "").strip()
    output_container = os.environ.get("GRAPH_OUTPUT_CONTAINER", "graphrag").strip()
    corpus_container = os.environ.get("CORPUS_CONTAINER_NAME", "corpus").strip()
    if not storage_account or not output_container or not corpus_container:
        raise HTTPException(status_code=503, detail="GraphRAG storage is not configured")
    try:
        config = _load_successful_run_config(
            storage_account,
            output_container,
            request.artifact_prefix,
            request.corpus_fingerprint,
        )
        manifest = _load_remote_corpus_manifest(storage_account, corpus_container)
        if manifest.get("corpus_fingerprint") != request.corpus_fingerprint:
            raise ValueError("Canonical corpus fingerprint no longer matches the query run")
        result = await execute_graphrag_query(
            config=config,
            corpus_manifest=manifest,
            query=request.query,
            mode=request.mode,
            response_type=request.response_type,
            community_level=request.community_level,
            dynamic_community_selection=request.dynamic_community_selection,
        )
        return result.to_dict()
    except ValueError as exc:
        raise HTTPException(status_code=409, detail=str(exc)) from exc


@app.post("/index")
def start_index(request: IndexRequest, background_tasks: BackgroundTasks) -> dict[str, str]:
    try:
        validate_graphrag_run_scope(request.run_scope, request.max_documents)
        validate_graphrag_artifact_prefix(request.output_prefix)
    except (RuntimeError, ValueError) as exc:
        raise HTTPException(status_code=423, detail=str(exc)) from exc

    job_id = uuid.uuid4().hex
    started = _now()
    with _jobs_lock:
        _jobs[job_id] = {
            "job_id": job_id,
            "state": "queued",
            "message": "Queued",
            "started_at": started,
            "updated_at": started,
            "artifact_prefix": request.output_prefix or f"runs/pending/{job_id}",
            "run_scope": request.run_scope,
            "max_documents": request.max_documents,
            "error": "",
        }
    background_tasks.add_task(_run_index, job_id, request)
    return {"job_id": job_id, "state": "queued"}


@app.get("/index/{job_id}/status", response_model=JobStatus)
def get_status(job_id: str) -> dict[str, Any]:
    with _jobs_lock:
        if job_id in _jobs:
            return _jobs[job_id]
    storage_account = os.environ.get("STORAGE_ACCOUNT_NAME", "")
    output_container = os.environ.get("GRAPH_OUTPUT_CONTAINER", "graphrag")
    if storage_account:
        try:
            blob_service = _blob_service(storage_account)
            container = blob_service.get_container_client(output_container)
            data = container.download_blob(_status_blob_name(job_id)).readall()
            status = json.loads(data.decode("utf-8"))
            with _jobs_lock:
                _jobs[job_id] = dict(status)
            return status
        except Exception as exc:
            log.warning("Could not load job status %s from Blob: %s", job_id, exc)
    raise HTTPException(status_code=404, detail="Job not found")
