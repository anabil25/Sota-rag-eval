"""Idempotent postprovision data-plane setup for Retrieve."""

from __future__ import annotations

import json
import os
import subprocess
import sys
from pathlib import Path

REPO_ROOT = Path(__file__).resolve().parents[1]
CORE_SRC = REPO_ROOT / "retrieve-core" / "src"
if str(CORE_SRC) not in sys.path:
    sys.path.insert(0, str(CORE_SRC))

from retrieve.indexing.blob_upload import BlobMirrorPlan, upload_corpus  # noqa: E402
from retrieve.config import load_config  # noqa: E402
from retrieve.config_io import atomic_update_yaml  # noqa: E402
from retrieve.db import RetrieveDB  # noqa: E402
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
    plan = upload_corpus(
        str(corpus_dir),
        required("AZURE_STORAGE_ACCOUNT_NAME"),
        required("AZURE_STORAGE_CORPUS_CONTAINER"),
        dry_run=True,
    )
    if not isinstance(plan, BlobMirrorPlan):
        raise RuntimeError("Corpus mirror dry run did not return a plan")
    if plan.corpus_fingerprint != manifest["corpus_fingerprint"]:
        raise RuntimeError("Corpus mirror plan fingerprint does not match the manifest")
    if plan.unmanaged:
        raise RuntimeError(
            "Corpus mirror is blocked by unmanaged remote Markdown: "
            + ", ".join(plan.unmanaged[:5])
        )
    count = upload_corpus(
        str(corpus_dir),
        required("AZURE_STORAGE_ACCOUNT_NAME"),
        required("AZURE_STORAGE_CORPUS_CONTAINER"),
        expected_plan=plan,
    )
    if not isinstance(count, int) or count != manifest["document_count"]:
        raise RuntimeError(
            "Corpus synchronization count did not match the canonical manifest"
        )
    fingerprint = str(manifest["corpus_fingerprint"])
    set_azd_value("RETRIEVE_CORPUS_FINGERPRINT", fingerprint)
    print(f"[postprovision] synchronized {count} documents ({fingerprint[:12]}).")


def _output_contract() -> dict[str, str]:
    return {
        "subscription_id": required("AZURE_SUBSCRIPTION_ID"),
        "location": required("AZURE_LOCATION"),
        "resource_group": required("AZURE_RESOURCE_GROUP"),
        "resource_token": required("AZURE_RESOURCE_TOKEN"),
        "storage_account": required("AZURE_STORAGE_ACCOUNT_NAME"),
        "corpus_container": required("AZURE_STORAGE_CORPUS_CONTAINER"),
        "graph_output_container": required("AZURE_STORAGE_GRAPH_CONTAINER"),
        "ai_services_endpoint": required("AZURE_AI_SERVICES_ENDPOINT"),
        "search_endpoint": required("AZURE_SEARCH_ENDPOINT"),
        "chat_deployment": required("AZURE_OPENAI_CHAT_DEPLOYMENT"),
        "embedding_deployment": required("AZURE_OPENAI_EMBEDDING_DEPLOYMENT"),
        "graph_job_name": required("AZURE_GRAPHRAG_JOB_NAME"),
        "container_apps_environment": required("AZURE_CONTAINER_APPS_ENVIRONMENT_NAME"),
    }


def sync_local_runtime_contract() -> None:
    config_path = Path(
        os.environ.get("RETRIEVE_CONFIG_PATH", REPO_ROOT / "retrieve.yaml")
    ).resolve()
    cfg = load_config(config_path)
    db_path = Path(cfg.db_path)
    if not db_path.is_absolute():
        db_path = config_path.parent / db_path
    db = RetrieveDB(db_path)
    try:
        ui_session = db.get_generation_preferences("ui_session") or {}
        explicit = [
            name.strip()
            for name in os.environ.get("RETRIEVE_ARCHITECTURES", "").split(",")
            if name.strip()
        ]
        selected = (
            explicit or ui_session.get("selected_architectures") or cfg.architectures
        )
        architectures = [str(name) for name in selected if str(name).strip()]
        if not architectures:
            raise RuntimeError("No Retrieve architectures are selected")
        outputs = _output_contract()

        def update_config(raw: dict) -> dict:
            azure = dict(raw.get("azure") or {})
            azure.update(outputs)
            raw["azure"] = azure
            raw["architectures"] = architectures
            return raw

        atomic_update_yaml(config_path, update_config)

        common = {
            "subscription_id": outputs["subscription_id"],
            "location": outputs["location"],
            "resource_group": outputs["resource_group"],
            "resource_token": outputs["resource_token"],
            "storage_account": outputs["storage_account"],
            "corpus_container": outputs["corpus_container"],
            "graph_output_container": outputs["graph_output_container"],
            "ai_services_endpoint": outputs["ai_services_endpoint"],
            "search_endpoint": outputs["search_endpoint"],
            "embedding_model": outputs["embedding_deployment"],
            "llm_model": outputs["chat_deployment"],
        }
        for name in architectures:
            architecture_config = {
                **common,
                "index_name": f"ret-{outputs['resource_token']}-{name}",
            }
            if name == "graphrag":
                architecture_config.update(
                    {
                        "graph_job_name": outputs["graph_job_name"],
                        "graph_worker_environment": outputs[
                            "container_apps_environment"
                        ],
                        "graphrag_run_scope": "sample",
                        "graphrag_max_documents": 50,
                    }
                )
            elif name == "lightrag":
                architecture_config["lightrag_max_documents"] = 50
            existing = db.get_architecture(name)
            if (
                existing
                and existing["config"].get("resource_token")
                == outputs["resource_token"]
            ):
                architecture_id = int(existing["id"])
                db.conn.execute(
                    "UPDATE architectures SET config = ?, resources_provisioned = ?, "
                    "status = 'provisioned' WHERE id = ?",
                    (
                        json.dumps(architecture_config),
                        json.dumps(architecture_config),
                        architecture_id,
                    ),
                )
            else:
                architecture_id = db.register_architecture(name, architecture_config)
                db.conn.execute(
                    "UPDATE architectures SET resources_provisioned = ?, "
                    "status = 'provisioned' WHERE id = ?",
                    (json.dumps(architecture_config), architecture_id),
                )
        ui_session.update(
            {
                "architectures": architectures,
                "selected_architectures": architectures,
                "resource_group": outputs["resource_group"],
                "location": outputs["location"],
                "name_prefix": outputs["resource_token"],
                "provision_done": True,
            }
        )
        db.upsert_generation_preferences(ui_session, "ui_session")
        db.conn.commit()
    finally:
        db.close()
    print(
        "[postprovision] synchronized localhost runtime contract for "
        + ", ".join(architectures)
    )


def main() -> None:
    print("[postprovision] starting data-plane setup")
    upload_canonical_corpus()
    sync_local_runtime_contract()
    print("[postprovision] complete")


if __name__ == "__main__":
    try:
        main()
    except (RuntimeError, ValueError, subprocess.CalledProcessError) as exc:
        print(f"[postprovision] {exc}", file=sys.stderr)
        raise SystemExit(1) from exc
