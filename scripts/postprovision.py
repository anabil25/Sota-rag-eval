"""Idempotent postprovision data-plane setup for Retrieve."""

from __future__ import annotations

import json
import hashlib
import os
import shutil
import subprocess
import sys
import tempfile
import time
from contextlib import contextmanager
from pathlib import Path

REPO_ROOT = Path(__file__).resolve().parents[1]
CORE_SRC = REPO_ROOT / "retrieve-core" / "src"
if str(CORE_SRC) not in sys.path:
    sys.path.insert(0, str(CORE_SRC))

from retrieve.cli_process import resolve_cli_command  # noqa: E402
from retrieve.config import load_config  # noqa: E402
from retrieve.config_io import atomic_update_yaml  # noqa: E402
from retrieve.db import RetrieveDB  # noqa: E402
from retrieve.ingest.manifest import (  # noqa: E402
    MANIFEST_FILENAME,
    load_corpus_manifest,
)
from retrieve.graphrag_worker.protocol import parse_job_result  # noqa: E402
from retrieve.indexing.container_job import start_container_job  # noqa: E402


def required(name: str) -> str:
    value = os.environ.get(name, "").strip()
    if not value:
        raise RuntimeError(f"Missing required azd output: {name}")
    return value


def set_azd_value(name: str, value: str) -> None:
    subprocess.run(resolve_cli_command(["azd", "env", "set", name, value]), check=True)


def _truthy(name: str) -> bool:
    return os.environ.get(name, "").strip().lower() in {"1", "true", "yes"}


def graph_runtime_enabled() -> bool:
    job_name = os.environ.get("AZURE_GRAPHRAG_JOB_NAME", "").strip()
    environment_name = os.environ.get(
        "AZURE_CONTAINER_APPS_ENVIRONMENT_NAME", ""
    ).strip()
    if bool(job_name) != bool(environment_name):
        raise RuntimeError("GraphRAG runtime outputs are incomplete")
    return bool(job_name)


def storage_creation_time() -> str:
    account = _json_command(
        [
            "az",
            "storage",
            "account",
            "show",
            "--name",
            required("AZURE_STORAGE_ACCOUNT_NAME"),
            "--resource-group",
            required("AZURE_RESOURCE_GROUP"),
            "--subscription",
            required("AZURE_SUBSCRIPTION_ID"),
            "--output",
            "json",
            "--only-show-errors",
        ],
        "Storage account creation-time inspection",
    )
    creation_time = str(account.get("creationTime") or "").strip()
    if not creation_time:
        raise RuntimeError("Storage account has no creation time")
    return creation_time


def validate_private_corpus_attestation() -> None:
    expected = os.environ.get("RETRIEVE_CORPUS_STORAGE_CREATED_AT", "").strip()
    actual = storage_creation_time()
    if not expected or expected != actual:
        raise RuntimeError(
            "Private corpus is not attested for the current Storage account. "
            "Set AZURE_DEPLOY_GRAPH_RUNTIME=true once to seed it through Azure."
        )


def graph_image_tag() -> str:
    """Return a deterministic tag for the exact GraphRAG job build inputs."""
    core = REPO_ROOT / "retrieve-core"
    inputs = [
        REPO_ROOT / ".dockerignore",
        core / "Dockerfile.graphrag-job",
        core / "pyproject.toml",
    ]
    inputs.extend(sorted((core / "src").rglob("*")))
    digest = hashlib.sha256()
    for path in inputs:
        if not path.is_file():
            continue
        digest.update(path.relative_to(REPO_ROOT).as_posix().encode("utf-8"))
        digest.update(b"\0")
        digest.update(path.read_bytes())
        digest.update(b"\0")
    return digest.hexdigest()[:16]


def graph_seed_image_tag(worker_image: str, manifest: dict) -> str:
    """Return a deterministic tag for one transient corpus seed image."""
    digest = hashlib.sha256()
    digest.update(worker_image.encode("utf-8"))
    digest.update(b"\0")
    digest.update(
        json.dumps(
            manifest,
            ensure_ascii=False,
            separators=(",", ":"),
            sort_keys=True,
        ).encode("utf-8")
    )
    digest.update(b"\0")
    digest.update((REPO_ROOT / "retrieve-core" / "Dockerfile.graphrag-seed").read_bytes())
    return digest.hexdigest()[:16]


@contextmanager
def graph_build_context():
    with tempfile.TemporaryDirectory(prefix="retrieve-graphrag-build-") as temp_dir:
        context = Path(temp_dir)
        source_core = REPO_ROOT / "retrieve-core"
        target_core = context / "retrieve-core"
        target_core.mkdir()
        shutil.copy2(REPO_ROOT / ".dockerignore", context / ".dockerignore")
        shutil.copy2(
            source_core / "Dockerfile.graphrag-job",
            target_core / "Dockerfile.graphrag-job",
        )
        shutil.copy2(source_core / "pyproject.toml", target_core / "pyproject.toml")
        shutil.copytree(source_core / "src", target_core / "src")
        yield context


@contextmanager
def graph_seed_build_context(corpus_dir: Path):
    with tempfile.TemporaryDirectory(prefix="retrieve-graphrag-seed-build-") as temp_dir:
        context = Path(temp_dir)
        target_core = context / "retrieve-core"
        target_core.mkdir()
        shutil.copy2(
            REPO_ROOT / "retrieve-core" / "Dockerfile.graphrag-seed",
            target_core / "Dockerfile.graphrag-seed",
        )
        shutil.copytree(corpus_dir, context / "corpus")
        yield context


def _authorization_failure(output: str) -> bool:
    normalized = output.lower()
    return any(
        marker in normalized
        for marker in (
            "authorizationfailed",
            "authorization failure",
            "does not have authorization",
            "forbidden",
            "status code: 403",
        )
    )


def _run_with_auth_retry(
    command: list[str],
    operation: str,
    *,
    delays: tuple[int, ...] = (10, 20, 30, 60, 60),
) -> subprocess.CompletedProcess[str]:
    for attempt in range(len(delays) + 1):
        result = subprocess.run(
            resolve_cli_command(command),
            capture_output=True,
            text=True,
        )
        if result.returncode == 0:
            return result
        details = "\n".join(part for part in (result.stdout, result.stderr) if part)
        if attempt >= len(delays) or not _authorization_failure(details):
            raise RuntimeError(f"{operation} failed: {details.strip()}")
        delay = delays[attempt]
        print(
            f"[postprovision] {operation} authorization is not propagated; "
            f"retrying in {delay}s ({attempt + 1}/{len(delays)})."
        )
        time.sleep(delay)
    raise RuntimeError(f"{operation} failed after authorization retries")


def _json_command(command: list[str], operation: str) -> dict | list:
    result = _run_with_auth_retry(command, operation)
    try:
        return json.loads(result.stdout)
    except json.JSONDecodeError as exc:
        raise RuntimeError(f"{operation} returned invalid JSON") from exc


def _update_graph_job_image(image: str, operation: str) -> None:
    _run_with_auth_retry(
        [
            "az",
            "containerapp",
            "job",
            "update",
            "--resource-group",
            required("AZURE_RESOURCE_GROUP"),
            "--name",
            required("AZURE_GRAPHRAG_JOB_NAME"),
            "--image",
            image,
            "--output",
            "none",
        ],
        operation,
    )


def publish_graph_image() -> str:
    if _truthy("RETRIEVE_SKIP_GRAPH_IMAGE_BUILD"):
        print("[postprovision] skipping GraphRAG image build by request")
        return required("RETRIEVE_GRAPHRAG_IMAGE")
    registry = required("AZURE_CONTAINER_REGISTRY_NAME")
    registry_endpoint = required("AZURE_CONTAINER_REGISTRY_ENDPOINT")
    image = f"retrieve-graphrag:{graph_image_tag()}"
    with graph_build_context() as context:
        _run_with_auth_retry(
            [
                "az",
                "acr",
                "build",
                "--registry",
                registry,
                "--image",
                image,
                "--file",
                "retrieve-core/Dockerfile.graphrag-job",
                "--no-logs",
                str(context),
            ],
            "GraphRAG ACR build",
        )
    full_image = f"{registry_endpoint}/{image}"
    _update_graph_job_image(full_image, "GraphRAG job image update")
    set_azd_value("RETRIEVE_GRAPHRAG_IMAGE", full_image)
    print(f"[postprovision] published {full_image}")
    return full_image


@contextmanager
def temporary_graph_seed_image(
    worker_image: str,
    corpus_dir: Path,
    manifest: dict,
):
    registry = required("AZURE_CONTAINER_REGISTRY_NAME")
    registry_endpoint = required("AZURE_CONTAINER_REGISTRY_ENDPOINT")
    image = f"retrieve-graphrag-seed:{graph_seed_image_tag(worker_image, manifest)}"
    full_image = f"{registry_endpoint}/{image}"
    with graph_seed_build_context(corpus_dir) as context:
        _run_with_auth_retry(
            [
                "az",
                "acr",
                "build",
                "--registry",
                registry,
                "--image",
                image,
                "--file",
                "retrieve-core/Dockerfile.graphrag-seed",
                "--build-arg",
                f"WORKER_IMAGE={worker_image}",
                "--no-logs",
                str(context),
            ],
            "GraphRAG seed ACR build",
        )
    try:
        _update_graph_job_image(full_image, "GraphRAG seed image activation")
    except Exception:
        _run_with_auth_retry(
            [
                "az",
                "acr",
                "repository",
                "delete",
                "--name",
                registry,
                "--image",
                image,
                "--yes",
                "--output",
                "none",
            ],
            "GraphRAG unused seed image deletion",
        )
        raise
    try:
        yield full_image
    finally:
        _update_graph_job_image(worker_image, "GraphRAG worker image restoration")
        _run_with_auth_retry(
            [
                "az",
                "acr",
                "repository",
                "delete",
                "--name",
                registry,
                "--image",
                image,
                "--yes",
                "--output",
                "none",
            ],
            "GraphRAG seed image deletion",
        )


def approve_search_storage_private_link(
    *,
    delays: tuple[int, ...] = (5, 10, 10, 15, 20, 30, 30, 30),
) -> None:
    resource_group = required("AZURE_RESOURCE_GROUP")
    subscription_id = required("AZURE_SUBSCRIPTION_ID")
    search_service = required("AZURE_SEARCH_SERVICE_NAME")
    storage_account = required("AZURE_STORAGE_ACCOUNT_NAME")
    shared_link_name = "storage-blob"

    for attempt in range(len(delays) + 1):
        shared_link = _json_command(
            [
                "az",
                "search",
                "shared-private-link-resource",
                "show",
                "--name",
                shared_link_name,
                "--service-name",
                search_service,
                "--resource-group",
                resource_group,
                "--subscription",
                subscription_id,
                "--output",
                "json",
                "--only-show-errors",
            ],
            "Search shared private link inspection",
        )
        properties = shared_link.get("properties", {}) if isinstance(shared_link, dict) else {}
        status = str(properties.get("status", "")).lower()
        provisioning_state = str(properties.get("provisioningState", "")).lower()
        if status == "approved":
            print("[postprovision] Search private Blob connection is approved")
            return
        if status in {"rejected", "disconnected"} or provisioning_state == "failed":
            raise RuntimeError(
                f"Search private Blob connection failed ({status or provisioning_state})"
            )

        connections = _json_command(
            [
                "az",
                "network",
                "private-endpoint-connection",
                "list",
                "--name",
                storage_account,
                "--resource-group",
                resource_group,
                "--type",
                "Microsoft.Storage/storageAccounts",
                "--subscription",
                subscription_id,
                "--output",
                "json",
                "--only-show-errors",
            ],
            "Storage private endpoint connection inspection",
        )
        pending = [
            connection
            for connection in connections
            if isinstance(connection, dict)
            and str(
                (connection.get("properties", {}).get("privateLinkServiceConnectionState", {}))
                .get("status", "")
            ).lower()
            == "pending"
        ]
        if len(pending) > 1:
            raise RuntimeError("Multiple pending Storage private endpoints require manual review")
        if pending:
            connection_id = str(pending[0].get("id", ""))
            if not connection_id:
                raise RuntimeError("Pending Storage private endpoint has no resource ID")
            _run_with_auth_retry(
                [
                    "az",
                    "network",
                    "private-endpoint-connection",
                    "approve",
                    "--id",
                    connection_id,
                    "--description",
                    "Approved for Retrieve Search private corpus indexing.",
                    "--subscription",
                    subscription_id,
                    "--output",
                    "none",
                    "--only-show-errors",
                ],
                "Search Storage private endpoint approval",
            )

        if attempt < len(delays):
            time.sleep(delays[attempt])

    raise RuntimeError("Search private Blob connection did not become approved")


def _job_logs(job_name: str, execution_name: str) -> str:
    result = subprocess.run(
        resolve_cli_command(
            [
                "az",
                "containerapp",
                "job",
                "logs",
                "show",
                "--name",
                job_name,
                "--resource-group",
                required("AZURE_RESOURCE_GROUP"),
                "--execution",
                execution_name,
                "--container",
                "graphrag",
                "--tail",
                "100",
                "--subscription",
                required("AZURE_SUBSCRIPTION_ID"),
            ]
        ),
        capture_output=True,
        text=True,
    )
    return "\n".join(part.strip() for part in (result.stdout, result.stderr) if part.strip())


def upload_canonical_corpus(
    *,
    worker_image: str = "",
    delays: tuple[int, ...] = tuple(10 for _ in range(60)),
    retry_delays: tuple[int, ...] = (20,),
) -> None:
    corpus_dir = Path(os.environ.get("RETRIEVE_CORPUS_DIR", REPO_ROOT / "corpus"))
    if not (corpus_dir / MANIFEST_FILENAME).is_file():
        print(
            f"[postprovision] Canonical manifest not found in {corpus_dir}; "
            "skipping corpus upload until ingestion produces one."
        )
        return

    manifest = load_corpus_manifest(corpus_dir)
    worker_image = worker_image or required("RETRIEVE_GRAPHRAG_IMAGE")
    resource_group = required("AZURE_RESOURCE_GROUP")
    subscription_id = required("AZURE_SUBSCRIPTION_ID")
    job_name = required("AZURE_GRAPHRAG_JOB_NAME")
    terminal_states = {
        "succeeded",
        "failed",
        "cancelled",
        "canceled",
        "stopped",
        "timedout",
    }
    with temporary_graph_seed_image(worker_image, corpus_dir, manifest):
        last_failure = ""
        for seed_attempt in range(len(retry_delays) + 1):
            execution_name = start_container_job(
                job_name=job_name,
                resource_group=resource_group,
                subscription_id=subscription_id,
                environment=[
                    "GRAPH_WORKER_MODE=seed",
                    "BUNDLED_CORPUS_DIR=/app/corpus",
                ],
            )

            state = ""
            details = ""
            for attempt in range(len(delays) + 1):
                execution = _json_command(
                    [
                        "az",
                        "containerapp",
                        "job",
                        "execution",
                        "show",
                        "--resource-group",
                        resource_group,
                        "--name",
                        job_name,
                        "--job-execution-name",
                        execution_name,
                        "--subscription",
                        subscription_id,
                        "--output",
                        "json",
                        "--only-show-errors",
                    ],
                    "Azure-side corpus seed status",
                )
                properties = (
                    execution.get("properties", {}) if isinstance(execution, dict) else {}
                )
                state = str(properties.get("status") or execution.get("status") or "").lower()
                details = str(properties.get("statusDetails") or "")
                if state in terminal_states:
                    break
                if attempt < len(delays):
                    time.sleep(delays[attempt])
            if state == "succeeded":
                logs = _job_logs(job_name, execution_name)
                seed_result = parse_job_result(logs)
                if (
                    seed_result.get("kind") != "seed"
                    or seed_result.get("state") != "succeeded"
                    or seed_result.get("corpus_fingerprint")
                    != manifest["corpus_fingerprint"]
                    or seed_result.get("document_count") != manifest["document_count"]
                ):
                    raise RuntimeError("Azure-side corpus seed returned a mismatched result")
                break

            logs = _job_logs(job_name, execution_name)
            last_failure = (
                f"Azure-side corpus seed ended as {state or 'unknown'}: {details}\n{logs}"
            ).strip()
            if seed_attempt >= len(retry_delays):
                raise RuntimeError(last_failure)
            retry_delay = retry_delays[seed_attempt]
            print(
                f"[postprovision] corpus seed execution failed; retrying in "
                f"{retry_delay}s ({seed_attempt + 1}/{len(retry_delays)})."
            )
            time.sleep(retry_delay)

    count = int(manifest["document_count"])
    fingerprint = str(manifest["corpus_fingerprint"])
    set_azd_value("RETRIEVE_CORPUS_FINGERPRINT", fingerprint)
    set_azd_value("RETRIEVE_CORPUS_STORAGE_CREATED_AT", storage_creation_time())
    print(
        f"[postprovision] synchronized {count} documents through private Blob "
        f"({fingerprint[:12]})."
    )


def _output_contract() -> dict[str, str]:
    return {
        "subscription_id": required("AZURE_SUBSCRIPTION_ID"),
        "location": required("AZURE_LOCATION"),
        "resource_group": required("AZURE_RESOURCE_GROUP"),
        "resource_token": required("AZURE_RESOURCE_TOKEN"),
        "storage_account": required("AZURE_STORAGE_ACCOUNT_NAME"),
        "corpus_container": required("AZURE_STORAGE_CORPUS_CONTAINER"),
        "corpus_fingerprint": required("RETRIEVE_CORPUS_FINGERPRINT"),
        "graph_output_container": required("AZURE_STORAGE_GRAPH_CONTAINER"),
        "ai_services_endpoint": required("AZURE_AI_SERVICES_ENDPOINT"),
        "search_endpoint": required("AZURE_SEARCH_ENDPOINT"),
        "chat_deployment": required("AZURE_OPENAI_CHAT_DEPLOYMENT"),
        "embedding_deployment": required("AZURE_OPENAI_EMBEDDING_DEPLOYMENT"),
        "graph_job_name": os.environ.get("AZURE_GRAPHRAG_JOB_NAME", "").strip(),
        "container_apps_environment": os.environ.get(
            "AZURE_CONTAINER_APPS_ENVIRONMENT_NAME", ""
        ).strip(),
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
        final_winners = (
            ui_session.get("winners", []) if ui_session.get("teardown_done") else []
        )
        selected = (
            explicit
            or final_winners
            or ui_session.get("selected_architectures")
            or cfg.architectures
        )
        architectures = [str(name) for name in selected if str(name).strip()]
        if not architectures:
            raise RuntimeError("No Retrieve architectures are selected")
        outputs = _output_contract()
        if "graphrag" in architectures and not outputs["graph_job_name"]:
            raise RuntimeError(
                "GraphRAG is selected but AZURE_DEPLOY_GRAPH_RUNTIME is false"
            )

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
            "corpus_fingerprint": outputs["corpus_fingerprint"],
            "graph_output_container": outputs["graph_output_container"],
            "ai_services_endpoint": outputs["ai_services_endpoint"],
            "search_endpoint": outputs["search_endpoint"],
            "embedding_model": outputs["embedding_deployment"],
            "llm_model": outputs["chat_deployment"],
        }
        for name in architectures:
            provisioned_config = {
                **common,
                "index_name": f"ret-{outputs['resource_token']}-{name}",
            }
            architecture_defaults: dict[str, object] = {}
            if name == "graphrag":
                provisioned_config.update(
                    {
                        "graph_job_name": outputs["graph_job_name"],
                        "graph_worker_environment": outputs[
                            "container_apps_environment"
                        ],
                    }
                )
                architecture_defaults.update(
                    {
                        "graphrag_run_scope": "sample",
                        "graphrag_max_documents": 50,
                    }
                )
            elif name == "lightrag":
                architecture_defaults["lightrag_max_documents"] = 50
            existing = db.get_architecture(name)
            if (
                existing
                and existing["config"].get("resource_token")
                == outputs["resource_token"]
            ):
                architecture_id = int(existing["id"])
                architecture_config = {
                    **existing["config"],
                    **provisioned_config,
                }
                resources_provisioned = {
                    **existing["resources_provisioned"],
                    **provisioned_config,
                }
                for key, value in architecture_defaults.items():
                    architecture_config.setdefault(key, value)
                    resources_provisioned.setdefault(key, value)
                status = (
                    existing["status"]
                    if existing["status"] in {"active", "indexing"}
                    else "provisioned"
                )
                db.conn.execute(
                    "UPDATE architectures SET config = ?, resources_provisioned = ?, "
                    "status = ? WHERE id = ?",
                    (
                        json.dumps(architecture_config),
                        json.dumps(resources_provisioned),
                        status,
                        architecture_id,
                    ),
                )
            else:
                architecture_config = {
                    **provisioned_config,
                    **architecture_defaults,
                }
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
    graph_enabled = graph_runtime_enabled()
    worker_image = publish_graph_image() if graph_enabled else ""
    approve_search_storage_private_link()
    if graph_enabled:
        upload_canonical_corpus(worker_image=worker_image)
    else:
        validate_private_corpus_attestation()
        print("[postprovision] reusing attested private Blob corpus")
    sync_local_runtime_contract()
    print("[postprovision] complete")


if __name__ == "__main__":
    try:
        main()
    except (RuntimeError, ValueError, subprocess.CalledProcessError) as exc:
        print(f"[postprovision] {exc}", file=sys.stderr)
        raise SystemExit(1) from exc
