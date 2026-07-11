"""Idempotent postprovision data-plane setup for Retrieve."""

from __future__ import annotations

import os
import subprocess
import sys
from pathlib import Path

REPO_ROOT = Path(__file__).resolve().parents[1]
CORE_SRC = REPO_ROOT / "retrieve-core" / "src"
if str(CORE_SRC) not in sys.path:
    sys.path.insert(0, str(CORE_SRC))

from retrieve.indexing.blob_upload import upload_corpus  # noqa: E402
from retrieve.ingest.manifest import (  # noqa: E402
    MANIFEST_FILENAME,
    load_corpus_manifest,
)


def required(name: str) -> str:
    value = os.environ.get(name, "").strip()
    if not value:
        raise RuntimeError(f"Missing required azd output: {name}")
    return value


def set_azd_value(name: str, value: str) -> None:
    subprocess.run(["azd", "env", "set", name, value], check=True)


def upload_canonical_corpus() -> None:
    corpus_dir = Path(os.environ.get("RETRIEVE_CORPUS_DIR", REPO_ROOT / "corpus"))
    if not (corpus_dir / MANIFEST_FILENAME).is_file():
        print(
            f"[postprovision] Canonical manifest not found in {corpus_dir}; "
            "skipping corpus upload until ingestion produces one."
        )
        return

    manifest = load_corpus_manifest(corpus_dir)
    count = upload_corpus(
        str(corpus_dir),
        required("AZURE_STORAGE_ACCOUNT_NAME"),
        required("AZURE_STORAGE_CORPUS_CONTAINER"),
    )
    if not isinstance(count, int) or count != manifest["document_count"]:
        raise RuntimeError(
            "Corpus synchronization count did not match the canonical manifest"
        )
    fingerprint = str(manifest["corpus_fingerprint"])
    set_azd_value("RETRIEVE_CORPUS_FINGERPRINT", fingerprint)
    print(f"[postprovision] synchronized {count} documents ({fingerprint[:12]}).")


def main() -> None:
    print("[postprovision] starting data-plane setup")
    upload_canonical_corpus()
    print("[postprovision] complete")


if __name__ == "__main__":
    try:
        main()
    except (RuntimeError, ValueError, subprocess.CalledProcessError) as exc:
        print(f"[postprovision] {exc}", file=sys.stderr)
        raise SystemExit(1) from exc