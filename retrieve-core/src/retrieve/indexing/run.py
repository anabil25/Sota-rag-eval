"""Indexing orchestrator — uploads corpus and creates search indexes.

References: docs/reference/skills/azure-blob-storage.md,
    docs/reference/skills/azure-ai-search.md, and
    docs/reference/skills/azure-indexer-pipeline.md
"""

from __future__ import annotations

import json
import logging
import os
import time
from typing import Any

from rich.console import Console

from retrieve.config import RetrieveConfig
from retrieve.db import RetrieveDB
from retrieve.indexing.blob_upload import BlobMirrorPlan, upload_corpus
from retrieve.indexing.search_index import (
    create_index_for_architecture,
    rerun_indexer,
    wait_for_indexer,
)
from retrieve.ingest.manifest import build_document_id_aliases, load_corpus_manifest
from retrieve.observability import emit_error, emit_progress, step

log = logging.getLogger(__name__)
console = Console()

# Architectures that use AI Foundry embeddings and need role propagation
_NEEDS_AI_SERVICES = {
    "single-vector",
    "hybrid",
    "hybrid-reranker",
    "hybrid-llm-enriched",
    "agentic-kb",
}


def _indexer_wait_targets(architecture: str, index_name: str) -> list[tuple[str, str]]:
    """Return (indexer_name, stats_index_name) pairs created by an architecture."""
    if architecture == "agentic-kb":
        base_index = f"{index_name}-base"
        return [(f"{base_index}-indexer", base_index)]
    if architecture in {"graphrag", "lightrag"}:
        return []
    return [(f"{index_name}-indexer", index_name)]


def _grounded_eval_sample_contract(db: RetrieveDB, corpus_dir: str) -> dict[str, Any]:
    """Return the active eval set's canonical graph-sampling contract."""
    from retrieve.eval.runner import _canonical_doc_id, _retrieval_questions

    session = db.get_generation_preferences("ui_session") or {}
    version = str(session.get("active_eval_set") or "").strip()
    eval_set = db.get_eval_set_by_version(version) if version else db.get_latest_eval_set()
    if version and not eval_set:
        raise ValueError(f"Active eval set does not exist: {version}")
    manifest = load_corpus_manifest(corpus_dir)
    if not eval_set:
        return {
            "eval_set_id": None,
            "eval_set_version": "",
            "corpus_fingerprint": str(manifest["corpus_fingerprint"]),
            "required_document_ids": [],
        }
    aliases = build_document_id_aliases(manifest)
    known = {str(document["document_id"]) for document in manifest["documents"]}
    required: list[str] = []
    for question in _retrieval_questions(db.get_questions(int(eval_set["id"]))):
        for chunk_id in question["ground_truth_chunk_ids"]:
            document_id = _canonical_doc_id(str(chunk_id), aliases)
            if document_id not in known:
                raise ValueError(f"Eval evidence is absent from the canonical corpus: {chunk_id}")
            if document_id not in required:
                required.append(document_id)
    return {
        "eval_set_id": int(eval_set["id"]),
        "eval_set_version": str(eval_set["version_label"]),
        "corpus_fingerprint": str(manifest["corpus_fingerprint"]),
        "required_document_ids": required,
    }


def index_corpus(cfg: RetrieveConfig, *, dry_run: bool = False):
    """Upload corpus to blob and create search indexes for all provisioned architectures."""
    db = RetrieveDB(cfg.db_path)
    async_indexing: list[dict[str, Any]] = []
    failed_architecture_ids: set[int] = set()
    indexing_architecture_ids: set[int] = set()

    try:
        # Find provisioned architectures
        provisioned: list[dict[str, Any]] = []
        for arch_name in cfg.architectures:
            arch = db.get_architecture(arch_name)
            if arch and arch["status"] in ("provisioned", "active"):
                provisioned.append(arch)
            else:
                console.print(
                    f"  [yellow]{arch_name}: not provisioned — "
                    "run 'retrieve provision' first[/yellow]"
                )

        if not provisioned:
            console.print(
                "[red]No provisioned architectures found. Run 'retrieve provision' first.[/red]"
            )
            return

        # Get storage info from first architecture config
        first_config = provisioned[0]["config"]
        storage_account = first_config.get("storage_account", "")
        if not storage_account:
            console.print("[red]No storage account in architecture config.[/red]")
            return

        # 1. Upload corpus to blob
        console.print("\n[bold]Step 1: Upload corpus to blob[/bold]")
        corpus_dir = cfg.corpus.output_dir
        graph_sample_contract = (
            _grounded_eval_sample_contract(db, corpus_dir)
            if any(arch["name"] in {"graphrag", "lightrag"} for arch in provisioned)
            else {}
        )
        required_graph_documents = graph_sample_contract.get("required_document_ids", [])
        synchronized_fingerprint = str(first_config.get("corpus_fingerprint") or "")
        local_fingerprint = ""
        if synchronized_fingerprint:
            local_fingerprint = str(load_corpus_manifest(corpus_dir)["corpus_fingerprint"])
        reuse_private_seed = (
            not dry_run
            and synchronized_fingerprint
            and synchronized_fingerprint == local_fingerprint
        )
        if reuse_private_seed:
            synchronization = int(load_corpus_manifest(corpus_dir)["document_count"])
            emit_progress(
                "Reusing attested private Blob corpus",
                stage="index.upload.reuse",
                file_count=synchronization,
                corpus_fingerprint=local_fingerprint,
            )
        else:
            with step("index.upload_corpus"):
                synchronization = upload_corpus(
                    corpus_dir,
                    storage_account,
                    dry_run=dry_run,
                )
        if isinstance(synchronization, BlobMirrorPlan):
            emit_progress(
                "Blob corpus mirror dry run complete",
                stage="index.upload.dry_run",
                **synchronization.to_dict(),
            )
            return {"blob_mirror_plan": synchronization.to_dict(), "dry_run": True}
        if synchronization == 0:
            return
        if not reuse_private_seed:
            emit_progress(
                f"Synchronized {synchronization} managed files",
                stage="index.upload",
                file_count=synchronization,
            )

        # 2. Create indexes per architecture
        console.print("\n[bold]Step 2: Create search indexes[/bold]\n")
        resource_group = first_config.get("resource_group", cfg.azure.resource_group)
        for arch in provisioned:
            arch_config = arch["config"]
            with step("index.create_index", architecture=arch["name"]):
                try:
                    index_result = create_index_for_architecture(
                        arch_name=arch["name"],
                        endpoint=arch_config.get("search_endpoint", ""),
                        index_name=arch_config.get("index_name", ""),
                        ai_services_endpoint=arch_config.get("ai_services_endpoint", ""),
                        embedding_model=arch_config.get(
                            "embedding_model", "text-embedding-3-large"
                        ),
                        storage_account=storage_account,
                        resource_group=resource_group,
                        corpus_dir=str(corpus_dir),
                        cosmos_endpoint=arch_config.get("cosmos_endpoint", ""),
                        function_endpoint=arch_config.get("function_endpoint", ""),
                        graph_worker_endpoint=arch_config.get("graph_worker_endpoint", ""),
                        graph_job_name=arch_config.get("graph_job_name", ""),
                        subscription_id=arch_config.get(
                            "subscription_id", cfg.azure.subscription_id
                        ),
                        container_app_endpoint=arch_config.get("container_app_endpoint", ""),
                        cohere_uri=arch_config.get("cohere_uri", ""),
                        cohere_model_name=arch_config.get("cohere_model_name", ""),
                        cohere_key=arch_config.get("cohere_key", "")
                        or os.environ.get("RETRIEVE_COHERE_KEY", ""),
                        custom_embedding_uri=arch_config.get("custom_embedding_uri", "")
                        or os.environ.get("RETRIEVE_CUSTOM_EMBEDDING_URI", ""),
                        custom_embedding_key=arch_config.get("custom_embedding_key", "")
                        or os.environ.get("RETRIEVE_CUSTOM_EMBEDDING_KEY", ""),
                        custom_embedding_dimensions=int(
                            arch_config.get("custom_embedding_dimensions", 0)
                            or os.environ.get("RETRIEVE_CUSTOM_EMBEDDING_DIMENSIONS", "0")
                        ),
                        custom_embedding_header_name=arch_config.get(
                            "custom_embedding_header_name", ""
                        )
                        or os.environ.get("RETRIEVE_CUSTOM_EMBEDDING_HEADER", "api-key"),
                        graphrag_run_scope=str(arch_config.get("graphrag_run_scope", "sample")),
                        graphrag_max_documents=(
                            int(arch_config.get("graphrag_max_documents", 50))
                            if arch_config.get("graphrag_max_documents", 50) is not None
                            else None
                        ),
                        graphrag_chunk_size=(
                            int(arch_config["graphrag_chunk_size"])
                            if arch_config.get("graphrag_chunk_size")
                            else None
                        ),
                        graphrag_chunk_overlap=(
                            int(arch_config["graphrag_chunk_overlap"])
                            if arch_config.get("graphrag_chunk_overlap") not in (None, "")
                            else None
                        ),
                        graphrag_required_document_ids=required_graph_documents,
                        lightrag_max_documents=int(arch_config.get("lightrag_max_documents", 50)),
                        lightrag_required_document_ids=required_graph_documents,
                        lightrag_working_dir=str(
                            arch_config.get("lightrag_working_root", ".lightrag")
                        ),
                    )
                    if isinstance(index_result, dict):
                        if arch["name"] in {"graphrag", "lightrag"}:
                            index_result.update(
                                {
                                    "representative_eval_set_id": graph_sample_contract.get(
                                        "eval_set_id"
                                    ),
                                    "representative_eval_set_version": graph_sample_contract.get(
                                        "eval_set_version", ""
                                    ),
                                    "representative_corpus_fingerprint": graph_sample_contract.get(
                                        "corpus_fingerprint", ""
                                    ),
                                }
                            )
                        arch_config.update(index_result)
                        db.conn.execute(
                            "UPDATE architectures SET config = ?, "
                            "resources_provisioned = ? WHERE id = ?",
                            (json.dumps(arch_config), json.dumps(arch_config), arch["id"]),
                        )
                        db.conn.commit()
                        cloud_status = str(index_result.get("cloud_index_status") or "").lower()
                        if cloud_status:
                            async_indexing.append({"architecture": arch["name"], **index_result})
                            if cloud_status in {"failed", "error"}:
                                failed_architecture_ids.add(int(arch["id"]))
                            elif cloud_status not in {"succeeded", "success", "completed"}:
                                indexing_architecture_ids.add(int(arch["id"]))
                except RuntimeError as e:
                    if arch["name"] == "graphrag" and "cloud index endpoint" in str(e):
                        console.print(f"  [yellow]{e}[/yellow]")
                        emit_error(str(e), e, stage="index.create", architecture=arch["name"])
                        failed_architecture_ids.add(int(arch["id"]))
                        continue
                    raise
            emit_progress(
                f"Created index for {arch['name']}",
                stage="index.create",
                architecture=arch["name"],
            )

        # 3. Wait for indexers — with retry for role propagation
        #
        # Architectures that use AI Foundry embeddings (hybrid, etc.) may fail
        # on first run because the Cognitive Services OpenAI User role on
        # Search's managed identity hasn't propagated yet. Strategy:
        #   - Wait 3 minutes initial (minimum propagation time)
        #   - Then poll: run indexer, wait, check if all docs failed
        #   - If all failed, re-run after 1 min (up to 5 retries = ~8 min total)
        needs_ai = any(a["name"] in _NEEDS_AI_SERVICES for a in provisioned)
        if needs_ai:
            console.print("\n[bold]Step 3: Waiting for RBAC role propagation (3 min)...[/bold]")
            with step("index.wait_rbac_propagation"):
                for elapsed in range(18):  # 18 x 10s = 180s = 3 min
                    emit_progress(
                        f"RBAC propagation wait ({(elapsed + 1) * 10}s / 180s)",
                        stage="index.rbac_wait",
                    )
                    time.sleep(10)

        console.print("\n[bold]Step 4: Waiting for indexers[/bold]\n")
        for arch in provisioned:
            arch_config = arch["config"]
            endpoint = arch_config.get("search_endpoint", "")
            index_name = arch_config.get("index_name", "")
            if not (endpoint and index_name):
                continue
            targets = _indexer_wait_targets(arch["name"], index_name)
            if not targets:
                continue

            for indexer_name, stats_index_name in targets:
                with step("index.wait_indexer", architecture=arch["name"]):
                    result = wait_for_indexer(endpoint, indexer_name)
                emit_progress(
                    f"Indexer '{indexer_name}': {result['status']} — "
                    f"{result['item_count']} items, {result['failed_count']} failed",
                    stage="index.wait_indexer",
                    architecture=arch["name"],
                    item_count=result["item_count"],
                    failed_count=result["failed_count"],
                )

                # Retry logic for AI-dependent architectures with total failure.
                # Two failure modes to detect:
                #   A) All items failed (failed_count == item_count > 0)
                #   B) 0 items, 0 failed but index has 0 docs
                needs_retry = False
                if arch["name"] in _NEEDS_AI_SERVICES:
                    if (
                        result["failed_count"] > 0
                        and result["failed_count"] == result["item_count"]
                    ):
                        needs_retry = True
                    elif result["item_count"] == 0 and result["failed_count"] == 0:
                        try:
                            from azure.identity import DefaultAzureCredential
                            from azure.search.documents.indexes import SearchIndexClient

                            _cred = DefaultAzureCredential()
                            _idx_client = SearchIndexClient(endpoint, _cred)
                            _stats = _idx_client.get_index_statistics(stats_index_name)
                            _doc_count = (
                                _stats.get("document_count", 0)
                                if isinstance(_stats, dict)
                                else getattr(_stats, "document_count", 0)
                            )
                            if _doc_count == 0:
                                console.print(
                                    f"  [yellow]Index '{stats_index_name}' has 0 documents — "
                                    "embedding skill may have failed[/yellow]"
                                )
                                needs_retry = True
                        except Exception:
                            pass

                if needs_retry:
                    sample_msgs = " ".join(e.get("message", "") for e in result.get("errors", []))
                    is_permission_error = any(
                        tok in sample_msgs.lower()
                        for tok in (
                            "unauthorized",
                            "403",
                            "forbidden",
                            "access denied",
                            "authentication",
                            "permission",
                        )
                    )
                    if not is_permission_error and result.get("errors"):
                        console.print(
                            "  [red]All docs failed with non-permission errors — "
                            "skipping retries (fix the skillset/index config).[/red]"
                        )
                    else:
                        for retry in range(5):
                            console.print(
                                f"  [yellow]Index empty or all docs failed "
                                f"(likely role propagation) — retrying in 60s "
                                f"(attempt {retry + 2}/6)...[/yellow]"
                            )
                            emit_progress(
                                f"Retry {retry + 2}/6 for {arch['name']} indexer",
                                stage="index.retry",
                                architecture=arch["name"],
                                retry_attempt=retry + 2,
                            )
                            time.sleep(60)
                            rerun_indexer(endpoint, indexer_name)
                            result = wait_for_indexer(endpoint, indexer_name)
                            if (
                                result["item_count"] > 0
                                and result["failed_count"] < result["item_count"]
                            ):
                                console.print(
                                    f"  [green]Retry succeeded — "
                                    f"{result['failed_count']} failures remaining[/green]"
                                )
                                break
                            try:
                                _stats = _idx_client.get_index_statistics(stats_index_name)
                                _doc_count = (
                                    _stats.get("document_count", 0)
                                    if isinstance(_stats, dict)
                                    else getattr(_stats, "document_count", 0)
                                )
                                if _doc_count > 0:
                                    console.print(
                                        f"  [green]Retry succeeded — {_doc_count} docs "
                                        "in index[/green]"
                                    )
                                    break
                            except Exception:
                                pass
                        else:
                            console.print(
                                f"  [red]Indexer '{indexer_name}' still failing "
                                "after 6 attempts[/red]"
                            )
                            failed_architecture_ids.add(int(arch["id"]))
                            emit_error(
                                f"Indexer '{indexer_name}' still failing after 6 attempts",
                                stage="index.retry",
                                architecture=arch["name"],
                            )

                if result.get("status") != "success" or result.get("failed_count", 0) > 0:
                    failed_architecture_ids.add(int(arch["id"]))

        # Update architecture status
        for arch in provisioned:
            architecture_id = int(arch["id"])
            if architecture_id in failed_architecture_ids:
                status = "failed"
            elif architecture_id in indexing_architecture_ids:
                status = "indexing"
            else:
                status = "active"
            db.conn.execute(
                "UPDATE architectures SET status = ? WHERE id = ?",
                (status, architecture_id),
            )
        db.conn.commit()

        console.print("\n[bold green]Indexing complete![/bold green]")
        if async_indexing:
            console.print(
                "[yellow]Graph-based cloud indexing is still running in the background. "
                "Refresh the UI to check the saved job handles.[/yellow]"
            )
        console.print("[dim]Next step: retrieve eval run[/dim]\n")
        return {"async_indexing": async_indexing}

    finally:
        db.close()
