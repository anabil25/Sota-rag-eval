"""Canonical corpus manifest generation and verification."""

from __future__ import annotations

import hashlib
import json
from datetime import UTC, datetime
from pathlib import Path
from typing import Any
from urllib.parse import urlsplit, urlunsplit

from retrieve.ingest.plugin import ConvertedDoc

MANIFEST_SCHEMA_VERSION = 1
MANIFEST_FILENAME = "corpus-manifest.json"
MANIFEST_BLOB_NAME = f"_retrieve/{MANIFEST_FILENAME}"


def _sha256_bytes(value: bytes) -> str:
    return hashlib.sha256(value).hexdigest()


def _graphrag_document_id(value: bytes) -> str:
    """Match GraphRAG TextFileReader's text-mode SHA-512 identity."""
    text = value.decode("utf-8").replace("\r\n", "\n").replace("\r", "\n")
    return hashlib.sha512(text.encode("utf-8"), usedforsecurity=False).hexdigest()


def content_sha256(markdown: str) -> str:
    """Hash canonical Markdown body content."""
    normalized = markdown.replace("\r\n", "\n").replace("\r", "\n")
    return _sha256_bytes(normalized.encode("utf-8"))


def normalize_source(source_url: str) -> str:
    """Normalize a URL or local path before deriving its stable source identity."""
    value = source_url.strip()
    parsed = urlsplit(value)
    if parsed.scheme.lower() in {"http", "https"} and parsed.netloc:
        normalized_path = parsed.path or "/"
        return urlunsplit(
            (
                parsed.scheme.lower(),
                parsed.netloc.lower(),
                normalized_path,
                parsed.query,
                "",
            )
        )
    return value.replace("\\", "/")


def logical_source_id(source_url: str, fallback: str = "") -> str:
    """Return a deterministic opaque identity for one authoritative source."""
    normalized = normalize_source(source_url) or f"document:{fallback}"
    return f"sha256:{_sha256_bytes(normalized.encode('utf-8'))}"


def build_manifest_entry(
    doc: ConvertedDoc,
    output_path: Path,
    corpus_root: Path,
) -> dict[str, str]:
    """Build a verified manifest entry for a saved document."""
    resolved_root = corpus_root.resolve()
    resolved_output = output_path.resolve()
    try:
        relative_path = resolved_output.relative_to(resolved_root).as_posix()
    except ValueError as exc:
        raise ValueError(f"Corpus document is outside the corpus root: {output_path}") from exc
    if not relative_path.lower().endswith(".md"):
        raise ValueError(f"Corpus manifest entries must be Markdown files: {relative_path}")

    file_bytes = resolved_output.read_bytes()
    document_id = str(doc.metadata.get("document_id") or doc.policy_id).strip()
    return {
        "document_id": document_id or logical_source_id(doc.source_url),
        "graphrag_document_id": _graphrag_document_id(file_bytes),
        "source_id": logical_source_id(doc.source_url, doc.policy_id),
        "source_url": normalize_source(doc.source_url),
        "relative_path": relative_path,
        "content_sha256": content_sha256(doc.markdown),
        "file_sha256": _sha256_bytes(file_bytes),
    }


def _fingerprint(entries: list[dict[str, Any]]) -> str:
    identity = [
        {
            "content_sha256": entry["content_sha256"],
            "document_id": entry["document_id"],
            "relative_path": entry["relative_path"],
            "source_id": entry["source_id"],
        }
        for entry in sorted(entries, key=lambda item: item["relative_path"])
    ]
    payload = json.dumps(identity, ensure_ascii=False, separators=(",", ":"), sort_keys=True)
    return _sha256_bytes(payload.encode("utf-8"))


def build_document_id_aliases(manifest: dict[str, Any]) -> dict[str, str]:
    """Map stable source/file aliases onto each canonical document ID."""
    aliases: dict[str, str] = {}
    ambiguous: set[str] = set()
    for entry in manifest.get("documents", []):
        canonical = str(entry.get("document_id") or "").strip()
        relative_path = str(entry.get("relative_path") or "").replace("\\", "/")
        source_id = str(entry.get("source_id") or "").strip()
        if not canonical or not relative_path:
            continue
        relative = Path(relative_path)
        candidates = {
            canonical,
            source_id,
            relative_path,
            str(relative.with_suffix("")).replace("\\", "/"),
            relative.name,
            relative.stem,
        }
        for candidate in {value for value in candidates if value}:
            existing = aliases.get(candidate)
            if existing is not None and existing != canonical:
                ambiguous.add(candidate)
            else:
                aliases[candidate] = canonical
    for candidate in ambiguous:
        aliases.pop(candidate, None)
    return aliases


def _validate_entry_uniqueness(entries: list[dict[str, Any]]) -> None:
    for key in ("document_id", "source_id", "relative_path"):
        values = [str(entry.get(key, "")) for entry in entries]
        if any(not value for value in values):
            raise ValueError(f"Corpus manifest contains an empty {key}")
        duplicates = sorted({value for value in values if values.count(value) > 1})
        if duplicates:
            raise ValueError(
                f"Corpus manifest contains duplicate {key} values: {', '.join(duplicates[:5])}"
            )


def _validate_relative_markdown_path(relative_path: str) -> Path:
    relative = Path(relative_path)
    if relative.is_absolute() or ".." in relative.parts or relative.suffix.lower() != ".md":
        raise ValueError(f"Unsafe corpus manifest path: {relative_path}")
    return relative


def validate_corpus_manifest_data(
    manifest: dict[str, Any],
    *,
    require_complete: bool = True,
) -> list[dict[str, Any]]:
    """Validate manifest structure and return its document entries."""
    if manifest.get("schema_version") != MANIFEST_SCHEMA_VERSION:
        raise ValueError(f"Unsupported corpus manifest schema: {manifest.get('schema_version')!r}")
    documents = manifest.get("documents")
    if not isinstance(documents, list):
        raise ValueError("Corpus manifest documents must be a list")
    _validate_entry_uniqueness(documents)
    for entry in documents:
        _validate_relative_markdown_path(str(entry["relative_path"]))
        for hash_name in ("content_sha256", "file_sha256"):
            value = str(entry.get(hash_name, ""))
            if len(value) != 64 or any(char not in "0123456789abcdef" for char in value):
                raise ValueError(f"Corpus manifest contains an invalid {hash_name}")
        graphrag_id = str(entry.get("graphrag_document_id", ""))
        if len(graphrag_id) != 128 or any(char not in "0123456789abcdef" for char in graphrag_id):
            raise ValueError("Corpus manifest contains an invalid graphrag_document_id")
    if int(manifest.get("document_count", -1)) != len(documents):
        raise ValueError("Corpus manifest document_count does not match documents")
    expected_fingerprint = _fingerprint(documents)
    if manifest.get("corpus_fingerprint") != expected_fingerprint:
        raise ValueError("Corpus manifest fingerprint does not match its documents")
    if require_complete and manifest.get("status") != "complete":
        raise ValueError("Corpus manifest is incomplete and cannot be uploaded")
    return documents


def write_corpus_manifest(
    corpus_root: Path,
    entries: list[dict[str, Any]],
    *,
    failed_sources: list[str] | None = None,
) -> dict[str, Any]:
    """Validate and atomically write the manifest for one ingestion generation."""
    root = corpus_root.resolve()
    sorted_entries = sorted(entries, key=lambda item: item["relative_path"])
    _validate_entry_uniqueness(sorted_entries)

    managed_paths = {str(entry["relative_path"]) for entry in sorted_entries}
    local_paths = {
        path.relative_to(root).as_posix() for path in root.rglob("*.md") if path.is_file()
    }
    stale = sorted(local_paths - managed_paths)
    missing = sorted(managed_paths - local_paths)
    if stale or missing:
        details = []
        if stale:
            details.append(f"stale/unmanaged={stale[:5]}")
        if missing:
            details.append(f"missing={missing[:5]}")
        raise ValueError("Corpus files do not match this generation: " + "; ".join(details))

    failures = sorted(set(failed_sources or []))
    manifest: dict[str, Any] = {
        "schema_version": MANIFEST_SCHEMA_VERSION,
        "status": "incomplete" if failures else "complete",
        "generated_at": datetime.now(UTC).isoformat(),
        "corpus_fingerprint": _fingerprint(sorted_entries),
        "document_count": len(sorted_entries),
        "failed_sources": failures,
        "documents": sorted_entries,
    }
    target = root / MANIFEST_FILENAME
    temporary = target.with_suffix(".json.tmp")
    temporary.write_text(
        json.dumps(manifest, ensure_ascii=False, indent=2) + "\n",
        encoding="utf-8",
    )
    temporary.replace(target)
    return manifest


def load_corpus_manifest(
    corpus_root: str | Path,
    *,
    require_complete: bool = True,
    verify_files: bool = True,
) -> dict[str, Any]:
    """Load and verify a local corpus manifest and its managed files."""
    root = Path(corpus_root).resolve()
    target = root / MANIFEST_FILENAME
    if not target.is_file():
        raise ValueError(f"Canonical corpus manifest not found: {target}")
    try:
        manifest = json.loads(target.read_text(encoding="utf-8"))
    except (OSError, json.JSONDecodeError) as exc:
        raise ValueError(f"Corpus manifest is not valid JSON: {target}") from exc
    if not isinstance(manifest, dict):
        raise ValueError("Corpus manifest must be a JSON object")
    documents = validate_corpus_manifest_data(
        manifest,
        require_complete=require_complete,
    )

    if verify_files:
        managed_paths: set[str] = set()
        for entry in documents:
            relative_path = str(entry["relative_path"])
            relative = _validate_relative_markdown_path(relative_path)
            path = (root / relative).resolve()
            try:
                path.relative_to(root)
            except ValueError as exc:
                raise ValueError(f"Corpus manifest path escapes root: {relative_path}") from exc
            if not path.is_file():
                raise ValueError(f"Corpus manifest file is missing: {relative_path}")
            file_bytes = path.read_bytes()
            if _sha256_bytes(file_bytes) != entry.get("file_sha256"):
                raise ValueError(f"Corpus manifest file hash mismatch: {relative_path}")
            if _graphrag_document_id(file_bytes) != entry.get("graphrag_document_id"):
                raise ValueError(f"Corpus GraphRAG document ID mismatch: {relative_path}")
            managed_paths.add(relative_path.replace("\\", "/"))

        local_paths = {
            path.relative_to(root).as_posix() for path in root.rglob("*.md") if path.is_file()
        }
        if local_paths != managed_paths:
            raise ValueError("Local Markdown files do not exactly match the corpus manifest")

    return manifest
