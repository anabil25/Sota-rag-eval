"""Blob uploader — uploads corpus .md files to Azure Blob Storage.

Reference: docs/reference/skills/azure-blob-storage.md
Uses Azure CLI identity locally and managed identity in Azure-hosted runs — no keys.
"""

from __future__ import annotations

import hashlib
import json
import logging
import os
import time
from concurrent.futures import ThreadPoolExecutor, as_completed
from dataclasses import dataclass
from pathlib import Path
from typing import Any

from azure.core.exceptions import HttpResponseError, ResourceNotFoundError
from azure.identity import AzureCliCredential, ChainedTokenCredential, ManagedIdentityCredential
from azure.storage.blob import BlobServiceClient, ContentSettings
from rich.console import Console
from rich.progress import Progress

from retrieve.ingest.manifest import (
    MANIFEST_BLOB_NAME,
    MANIFEST_FILENAME,
    load_corpus_manifest,
    validate_corpus_manifest_data,
)
from retrieve.observability import emit_progress

log = logging.getLogger(__name__)
console = Console()

_AUTH_RETRY_DELAYS_SECONDS = [10, 20, 30, 60, 60, 60]


@dataclass(frozen=True)
class BlobMirrorPlan:
    """No-write comparison between local and remotely managed corpus state."""

    corpus_fingerprint: str
    document_count: int
    uploads: tuple[str, ...]
    deletes: tuple[str, ...]
    unchanged: tuple[str, ...]
    unmanaged: tuple[str, ...]
    remote_manifest_found: bool

    def to_dict(self) -> dict[str, Any]:
        return {
            "corpus_fingerprint": self.corpus_fingerprint,
            "document_count": self.document_count,
            "uploads": list(self.uploads),
            "deletes": list(self.deletes),
            "unchanged": list(self.unchanged),
            "unmanaged": list(self.unmanaged),
            "remote_manifest_found": self.remote_manifest_found,
        }


def _build_credential() -> ChainedTokenCredential:
    """Use the configured user identity in Azure and Azure CLI locally."""
    client_id = os.environ.get("AZURE_CLIENT_ID", "").strip() or None
    managed_identity = ManagedIdentityCredential(client_id=client_id)
    azure_cli = AzureCliCredential()
    hosted = bool(os.environ.get("IDENTITY_ENDPOINT") or os.environ.get("MSI_ENDPOINT"))
    credentials = (managed_identity, azure_cli) if hosted else (azure_cli, managed_identity)
    return ChainedTokenCredential(*credentials)


def _is_auth_error(exc: Exception) -> bool:
    """Return True for transient data-plane auth failures during RBAC propagation."""
    if not isinstance(exc, HttpResponseError):
        return False
    msg = str(exc).lower()
    return any(tok in msg for tok in ("authorizationfailure", "unauthorized", "forbidden", "403"))


def _wait_for_blob_data_access(container_client) -> None:
    """Wait for data-plane RBAC to propagate for the active identity."""
    for attempt, delay in enumerate(_AUTH_RETRY_DELAYS_SECONDS, start=1):
        try:
            # Cheap data-plane call to validate Blob Data permissions.
            container_client.get_container_properties()
            return
        except Exception as exc:
            if not _is_auth_error(exc):
                raise
            console.print(
                "  [yellow]Blob data access not ready yet (RBAC propagation). "
                f"Retrying in {delay}s "
                f"(attempt {attempt}/{len(_AUTH_RETRY_DELAYS_SECONDS)})...[/yellow]"
            )
            emit_progress(
                f"Blob RBAC propagation wait (attempt {attempt}/{len(_AUTH_RETRY_DELAYS_SECONDS)})",
                stage="blob_upload.rbac_wait",
            )
            time.sleep(delay)

    # One final attempt so the caller gets the concrete Azure error payload.
    container_client.get_container_properties()


def _load_remote_manifest(container_client) -> dict[str, Any] | None:
    try:
        payload = container_client.download_blob(MANIFEST_BLOB_NAME).readall()
    except ResourceNotFoundError:
        return None
    except HttpResponseError as exc:
        if getattr(exc, "status_code", None) == 404:
            return None
        raise
    try:
        manifest = json.loads(bytes(payload).decode("utf-8"))
    except (TypeError, UnicodeDecodeError, json.JSONDecodeError) as exc:
        raise ValueError("Remote corpus manifest is not valid UTF-8 JSON") from exc
    if not isinstance(manifest, dict):
        raise ValueError("Remote corpus manifest must be a JSON object")
    validate_corpus_manifest_data(manifest)
    return manifest


def build_blob_mirror_plan(
    corpus_dir: str | Path,
    container_client,
) -> BlobMirrorPlan:
    """Build a no-write synchronization plan from local and remote manifests."""
    local_manifest = load_corpus_manifest(corpus_dir)
    remote_manifest = _load_remote_manifest(container_client)
    local_documents = {str(entry["relative_path"]): entry for entry in local_manifest["documents"]}
    remote_documents = {
        str(entry["relative_path"]): entry for entry in (remote_manifest or {}).get("documents", [])
    }
    existing_markdown = {
        str(getattr(blob, "name", blob))
        for blob in container_client.list_blobs()
        if str(getattr(blob, "name", blob)).lower().endswith(".md")
    }

    uploads = sorted(
        path
        for path, entry in local_documents.items()
        if remote_documents.get(path, {}).get("file_sha256") != entry["file_sha256"]
    )
    unchanged = sorted(set(local_documents) - set(uploads))
    # Only a prior valid Retrieve manifest grants ownership to delete a path.
    deletes = sorted(set(remote_documents) - set(local_documents))
    unmanaged = sorted(existing_markdown - set(remote_documents) - set(local_documents))
    return BlobMirrorPlan(
        corpus_fingerprint=str(local_manifest["corpus_fingerprint"]),
        document_count=len(local_documents),
        uploads=tuple(uploads),
        deletes=tuple(deletes),
        unchanged=tuple(unchanged),
        unmanaged=tuple(unmanaged),
        remote_manifest_found=remote_manifest is not None,
    )


def upload_corpus(
    corpus_dir: str,
    storage_account_name: str,
    container_name: str = "corpus",
    *,
    dry_run: bool = False,
    expected_plan: BlobMirrorPlan | None = None,
) -> int | BlobMirrorPlan:
    """Synchronize a verified canonical corpus with its Blob container.

    Deletions are limited to Markdown paths owned by the prior valid remote
    manifest. The new manifest is committed only after all file operations
    succeed. A dry run reads state and returns a plan without mutating Blob.
    """
    corpus_path = Path(corpus_dir)
    if not corpus_path.exists():
        console.print(f"[red]Corpus directory not found: {corpus_dir}[/red]")
        return 0

    if not any(corpus_path.rglob("*.md")):
        console.print("[red]No .md files found in corpus directory.[/red]")
        return 0

    local_manifest = load_corpus_manifest(corpus_path)
    documents = {str(entry["relative_path"]): entry for entry in local_manifest["documents"]}

    account_url = f"https://{storage_account_name}.blob.core.windows.net"
    credential = _build_credential()
    blob_service = BlobServiceClient(account_url=account_url, credential=credential)
    container_client = blob_service.get_container_client(container_name)
    _wait_for_blob_data_access(container_client)
    plan = build_blob_mirror_plan(corpus_path, container_client)
    if dry_run:
        console.print(
            f"  Blob mirror dry run: {len(plan.uploads)} upload(s), "
            f"{len(plan.deletes)} delete(s), {len(plan.unchanged)} unchanged, "
            f"{len(plan.unmanaged)} unmanaged"
        )
        return plan
    if expected_plan is not None and plan != expected_plan:
        raise ValueError(
            "Remote corpus state changed after the reviewed dry run; generate a new mirror plan"
        )
    if plan.deletes and expected_plan is None:
        raise ValueError(
            "Managed corpus deletions require an exact dry-run plan passed as expected_plan"
        )
    if plan.unmanaged:
        raise ValueError(
            "Remote corpus contains unmanaged Markdown that cannot be safely deleted: "
            f"{list(plan.unmanaged[:5])}. Run a dry-run and inventory/adopt the existing "
            "generation before mirroring."
        )

    md_settings = ContentSettings(content_type="text/markdown; charset=utf-8")
    json_settings = ContentSettings(content_type="application/json; charset=utf-8")

    console.print(
        f"\n  Synchronizing [green]{plan.document_count}[/green] managed files "
        f"to [cyan]{container_name}[/cyan]..."
    )

    def _upload_one(blob_name: str) -> None:
        filepath = corpus_path / Path(blob_name)
        payload = filepath.read_bytes()
        actual_hash = hashlib.sha256(payload).hexdigest()
        if actual_hash != documents[blob_name]["file_sha256"]:
            raise ValueError(f"Corpus file changed after manifest validation: {blob_name}")
        for attempt, delay in enumerate(_AUTH_RETRY_DELAYS_SECONDS, start=1):
            try:
                container_client.upload_blob(
                    name=blob_name,
                    data=payload,
                    content_settings=md_settings,
                    overwrite=True,
                )
                return
            except Exception as exc:
                if not _is_auth_error(exc):
                    raise
                if attempt == len(_AUTH_RETRY_DELAYS_SECONDS):
                    raise
                time.sleep(delay)

    if plan.uploads:
        with Progress() as progress:
            task = progress.add_task("Uploading...", total=len(plan.uploads))
            with ThreadPoolExecutor(max_workers=8) as pool:
                futures = {pool.submit(_upload_one, name): name for name in plan.uploads}
                for future in as_completed(futures):
                    future.result()
                    progress.advance(task)

    for blob_name in plan.deletes:
        container_client.delete_blob(blob_name, delete_snapshots="include")

    # Commit the new ownership boundary last. A failed file operation leaves the
    # previous remote manifest intact so a retry computes the same safe plan.
    container_client.upload_blob(
        name=MANIFEST_BLOB_NAME,
        data=(corpus_path / MANIFEST_FILENAME).read_bytes(),
        content_settings=json_settings,
        overwrite=True,
    )

    console.print(
        f"  [green]✓ {len(plan.uploads)} uploaded, {len(plan.deletes)} deleted, "
        f"{len(plan.unchanged)} unchanged[/green]"
    )
    emit_progress(
        f"{plan.document_count} managed corpus files synchronized",
        stage="blob_upload.complete",
        file_count=plan.document_count,
        uploaded_count=len(plan.uploads),
        deleted_count=len(plan.deletes),
        corpus_fingerprint=plan.corpus_fingerprint,
    )
    return plan.document_count
