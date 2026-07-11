"""Azure provisioning orchestrator — deploys Bicep templates per architecture.

Skills reference: skills/azure-bicep-iac.md, skills/azure-ai-search.md,
    skills/azure-ai-foundry.md, skills/azure-blob-storage.md, service-matrix.md

Deployment order (per service-matrix.md):
  1. Storage Account + Blob Container
  2. AI Foundry + model deployments (BEFORE Search)
  3. AI Search Service
  4. Role Assignments (Search→Blob, Search→OpenAI)
    5. Cosmos DB (GraphRAG only)
    6. Container Apps (GraphRAG worker / LightRAG server)
"""

from __future__ import annotations

import base64
import json
import logging
import os
import shutil
import subprocess
import time
from pathlib import Path
from typing import Any

import requests as http_requests
from rich.console import Console

from retrieve.config import RetrieveConfig
from retrieve.db import RetrieveDB
from retrieve.observability import emit_error, emit_progress, step
from retrieve.provision.naming import (
    build_deployment_names,
    candidate_resource_group_names,
    is_name_collision_error,
    resolve_deployment_names,
)
from retrieve.registry.architectures import ARCHITECTURES

log = logging.getLogger(__name__)
console = Console()

BICEP_DIR = Path(__file__).parent / "bicep"
RETRIEVE_CORE_DIR = Path(__file__).resolve().parents[3]
AZ_COMMAND = shutil.which("az.cmd") or shutil.which("az") or "az"
_AZ_CLI_TIMEOUT_SECONDS = 45
_DEPLOYMENT_START_TIMEOUT_SECONDS = 180
_DEPLOYMENT_OPERATION_TIMEOUT_SECONDS = 12
_DEPLOYMENT_CONTEXT_TIMEOUT_SECONDS = 45
_ARM_DEPLOYMENT_POLL_SECONDS = 10
_ARM_DEPLOYMENT_MAX_POLLS = 180
_STORAGE_BLOB_DATA_CONTRIBUTOR_ROLE_ID = "ba92f5b4-2d11-453d-a403-e96b0029c9fe"
_OPENAI_USER_ROLE_ID = "5e0bd9bd-7b93-4f28-af87-19fc36ad61bd"
_SEARCH_INDEX_DATA_READER_ROLE_ID = "1407120a-92aa-4202-b7e9-c0e197c71c8f"
_SEARCH_INDEX_DATA_CONTRIBUTOR_ROLE_ID = "8ebe5a00-799e-43f5-93ac-243d3dce84a7"
_SEARCH_SERVICE_CONTRIBUTOR_ROLE_ID = "7ca78c08-252a-4471-8644-bb5ff32d4ba0"
_COSMOS_SQL_DATA_READER_ROLE_ID = "00000000-0000-0000-0000-000000000001"
_COSMOS_SQL_DATA_CONTRIBUTOR_ROLE_ID = "00000000-0000-0000-0000-000000000002"
_GRAPH_WORKER_PROFILE_NAME = "graph-d4"
_GRAPH_WORKER_PROFILE_TYPE = "D4"
_GRAPH_WORKER_PROFILE_MIN_NODES = "1"
_GRAPH_WORKER_PROFILE_MAX_NODES = "2"
_GRAPH_WORKER_CPU = "4"
_GRAPH_WORKER_MEMORY = "14Gi"


def _is_resource_group_deleting_error(error: Exception) -> bool:
    return "ResourceGroupBeingDeleted" in str(error)


def _is_existing_resource_group_location_error(error: Exception) -> bool:
    error_text = str(error)
    return "InvalidResourceGroupLocation" in error_text and "already exists" in error_text


def _is_regional_capacity_error(error: Exception) -> bool:
    error_text = str(error).lower()
    capacity_markers = (
        "insufficientresourcesavailable",
        "regiondoesnotallowprovisioning",
        "skunotavailable",
        "allocationfailed",
        "insufficientquota",
        "serviceunavailable",
        "high demand",
        "quota tokens per minute",
        "cannot fulfill your request",
        "temporarily unavailable",
    )
    return any(marker in error_text for marker in capacity_markers)


def _ordered_regions(primary_region: str, fallback_regions: list[str]) -> list[str]:
    ordered: list[str] = []
    for region in [primary_region, *fallback_regions]:
        if region and region not in ordered:
            ordered.append(region)
    return ordered


def _az_json(args: list[str]) -> dict[str, Any]:
    """Run an az CLI command and return parsed JSON output."""
    cmd = [AZ_COMMAND] + args + ["-o", "json"]
    try:
        result = subprocess.run(
            cmd,
            capture_output=True,
            text=True,
            shell=False,
            timeout=_AZ_CLI_TIMEOUT_SECONDS,
        )
    except subprocess.TimeoutExpired as exc:
        raise RuntimeError(f"az {' '.join(args[:4])}... timed out") from exc
    if result.returncode != 0:
        raise RuntimeError(f"az {' '.join(args[:4])}... failed:\n{result.stderr.strip()}")
    return json.loads(result.stdout)


def _az_json_or_none(args: list[str]) -> Any | None:
    cmd = [AZ_COMMAND] + args + ["-o", "json"]
    try:
        result = subprocess.run(
            cmd,
            capture_output=True,
            text=True,
            shell=False,
            timeout=_AZ_CLI_TIMEOUT_SECONDS,
        )
    except subprocess.TimeoutExpired as exc:
        raise RuntimeError(f"az {' '.join(args[:4])}... timed out") from exc
    if result.returncode != 0:
        error_text = result.stderr.strip()
        if any(
            marker in error_text
            for marker in ("ResourceNotFound", "was not found", "could not be found")
        ):
            return None
        raise RuntimeError(f"az {' '.join(args[:4])}... failed:\n{error_text}")
    if not result.stdout.strip():
        return None
    return json.loads(result.stdout)


def _az_run(args: list[str], timeout: int = _AZ_CLI_TIMEOUT_SECONDS) -> str:
    """Run an az CLI command that may not emit JSON."""
    try:
        result = subprocess.run(
            [AZ_COMMAND] + args,
            capture_output=True,
            text=True,
            shell=False,
            timeout=timeout,
        )
    except subprocess.TimeoutExpired as exc:
        raise RuntimeError(f"az {' '.join(args[:4])}... timed out") from exc
    if result.returncode != 0:
        raise RuntimeError(f"az {' '.join(args[:4])}... failed:\n{result.stderr.strip()}")
    return result.stdout.strip()


def _assign_arm_role(scope: str, principal_id: str, role_id: str, label: str) -> None:
    if not scope or not principal_id:
        return
    result = subprocess.run(
        [
            AZ_COMMAND,
            "role",
            "assignment",
            "create",
            "--assignee-object-id",
            principal_id,
            "--assignee-principal-type",
            "ServicePrincipal",
            "--role",
            role_id,
            "--scope",
            scope,
            "-o",
            "none",
        ],
        capture_output=True,
        text=True,
        shell=False,
        timeout=_AZ_CLI_TIMEOUT_SECONDS,
    )
    if result.returncode == 0 or "RoleAssignmentExists" in result.stderr:
        return
    raise RuntimeError(f"Failed to assign {label}: {result.stderr.strip()}")


def _assign_cosmos_sql_role(
    resource_group: str,
    cosmos_account: str,
    principal_id: str,
    role_id: str,
    label: str,
) -> None:
    if not (resource_group and cosmos_account and principal_id):
        return
    account = _az_json(["cosmosdb", "show", "-g", resource_group, "-n", cosmos_account])
    account_id = str(account.get("id") or "")
    role_definition_id = f"{account_id}/sqlRoleDefinitions/{role_id}"

    existing = _az_json([
        "cosmosdb", "sql", "role", "assignment", "list",
        "-g", resource_group,
        "-a", cosmos_account,
    ])
    if isinstance(existing, list):
        for assignment in existing:
            if (
                str(assignment.get("principalId", "")).lower() == principal_id.lower()
                and str(assignment.get("roleDefinitionId", "")).lower()
                == role_definition_id.lower()
            ):
                return

    result = subprocess.run(
        [
            AZ_COMMAND,
            "cosmosdb",
            "sql",
            "role",
            "assignment",
            "create",
            "-g",
            resource_group,
            "-a",
            cosmos_account,
            "--scope",
            "/",
            "--principal-id",
            principal_id,
            "--role-definition-id",
            role_definition_id,
            "-o",
            "none",
        ],
        capture_output=True,
        text=True,
        shell=False,
        timeout=_AZ_CLI_TIMEOUT_SECONDS,
    )
    if result.returncode == 0 or "already exists" in result.stderr.lower():
        return
    raise RuntimeError(f"Failed to assign {label}: {result.stderr.strip()}")


def _deploy_graphrag_worker_container(
    resource_group: str,
    location: str,
    environment_name: str,
    app_name: str,
    storage_account: str,
    storage_account_id: str,
    ai_services_endpoint: str,
    ai_services_id: str,
    search_endpoint: str,
    search_service_id: str,
    cosmos_account: str,
    embedding_model: str,
) -> tuple[str, str]:
    """Build/update the Retrieve GraphRAG worker Container App from source."""
    if not environment_name or not app_name:
        return "", ""

    _ensure_graphrag_workload_environment(
        resource_group,
        location,
        environment_name,
        _GRAPH_WORKER_PROFILE_NAME,
        _GRAPH_WORKER_PROFILE_TYPE,
    )

    console.print("  [cyan]GraphRAG worker:[/cyan] building/updating Container App...")
    _az_run(
        [
            "containerapp",
            "up",
            "-g",
            resource_group,
            "-n",
            app_name,
            "--environment",
            environment_name,
            "--source",
            str(RETRIEVE_CORE_DIR),
            "--ingress",
            "internal",
            "--target-port",
            "8000",
            "--env-vars",
            f"STORAGE_ACCOUNT_NAME={storage_account}",
            "CORPUS_CONTAINER_NAME=corpus",
            "GRAPH_OUTPUT_CONTAINER=graphrag",
            "RETRIEVE_GRAPH_QUERY_ENABLED=true",
            f"AI_SERVICES_ENDPOINT={ai_services_endpoint}",
            f"SEARCH_ENDPOINT={search_endpoint}",
            "LLM_DEPLOYMENT_NAME=gpt-4.1",
            f"EMBEDDING_DEPLOYMENT_NAME={embedding_model}",
        ],
        timeout=int(os.environ.get("RETRIEVE_CONTAINERAPP_UP_TIMEOUT", "2400")),
    )
    _az_json([
        "containerapp",
        "update",
        "-g",
        resource_group,
        "-n",
        app_name,
        "--workload-profile-name",
        _GRAPH_WORKER_PROFILE_NAME,
        "--cpu",
        _GRAPH_WORKER_CPU,
        "--memory",
        _GRAPH_WORKER_MEMORY,
        "--min-replicas",
        "1",
        "--max-replicas",
        "1",
    ])

    identity = _az_json([
        "containerapp",
        "identity",
        "assign",
        "-g",
        resource_group,
        "-n",
        app_name,
        "--system-assigned",
    ])
    principal_id = str(identity.get("principalId") or "")
    if not principal_id:
        app_identity = identity.get("identity", {}) if isinstance(identity, dict) else {}
        principal_id = str(app_identity.get("principalId") or "")

    _assign_arm_role(
        storage_account_id,
        principal_id,
        _STORAGE_BLOB_DATA_CONTRIBUTOR_ROLE_ID,
        "Storage Blob Data Contributor to GraphRAG worker",
    )
    _assign_arm_role(
        ai_services_id,
        principal_id,
        _OPENAI_USER_ROLE_ID,
        "Cognitive Services OpenAI User to GraphRAG worker",
    )
    _assign_arm_role(
        search_service_id,
        principal_id,
        _SEARCH_INDEX_DATA_READER_ROLE_ID,
        "Search Index Data Reader to GraphRAG worker",
    )
    _assign_arm_role(
        search_service_id,
        principal_id,
        _SEARCH_INDEX_DATA_CONTRIBUTOR_ROLE_ID,
        "Search Index Data Contributor to GraphRAG worker",
    )
    _assign_arm_role(
        search_service_id,
        principal_id,
        _SEARCH_SERVICE_CONTRIBUTOR_ROLE_ID,
        "Search Service Contributor to GraphRAG worker",
    )
    _assign_cosmos_sql_role(
        resource_group,
        cosmos_account,
        principal_id,
        _COSMOS_SQL_DATA_CONTRIBUTOR_ROLE_ID,
        "Cosmos DB Built-in Data Contributor to GraphRAG worker",
    )

    _az_json([
        "containerapp",
        "update",
        "-g",
        resource_group,
        "-n",
        app_name,
        "--workload-profile-name",
        _GRAPH_WORKER_PROFILE_NAME,
        "--cpu",
        _GRAPH_WORKER_CPU,
        "--memory",
        _GRAPH_WORKER_MEMORY,
        "--min-replicas",
        "1",
        "--max-replicas",
        "1",
        "--set-env-vars",
        f"RETRIEVE_GRAPH_WORKER_RESTART={int(time.time())}",
    ])

    app = _az_json(["containerapp", "show", "-g", resource_group, "-n", app_name])
    fqdn = (
        app.get("properties", {})
        .get("configuration", {})
        .get("ingress", {})
        .get("fqdn", "")
    )
    endpoint = f"https://{fqdn}" if fqdn else ""
    return endpoint, principal_id


def _ensure_graphrag_workload_environment(
    resource_group: str,
    location: str,
    environment_name: str,
    profile_name: str,
    profile_type: str,
) -> None:
    """Ensure GraphRAG has a dedicated high-memory Container Apps profile."""
    console.print(
        "  [cyan]GraphRAG worker:[/cyan] ensuring dedicated Container Apps profile..."
    )
    environment = _az_json_or_none([
        "containerapp",
        "env",
        "show",
        "-g",
        resource_group,
        "-n",
        environment_name,
    ])
    if not environment:
        _az_run(
            [
                "containerapp",
                "env",
                "create",
                "-g",
                resource_group,
                "-n",
                environment_name,
                "-l",
                location,
                "--enable-workload-profiles",
                "true",
                "-o",
                "none",
            ],
            timeout=900,
        )

    profile = _az_json_or_none([
        "containerapp",
        "env",
        "workload-profile",
        "show",
        "-g",
        resource_group,
        "-n",
        environment_name,
        "--workload-profile-name",
        profile_name,
    ])
    if not profile:
        _az_run(
            [
                "containerapp",
                "env",
                "workload-profile",
                "add",
                "-g",
                resource_group,
                "-n",
                environment_name,
                "--workload-profile-name",
                profile_name,
                "--workload-profile-type",
                profile_type,
                "--min-nodes",
                _GRAPH_WORKER_PROFILE_MIN_NODES,
                "--max-nodes",
                _GRAPH_WORKER_PROFILE_MAX_NODES,
                "-o",
                "none",
            ],
            timeout=900,
        )
    else:
        _az_run(
            [
                "containerapp",
                "env",
                "workload-profile",
                "update",
                "-g",
                resource_group,
                "-n",
                environment_name,
                "--workload-profile-name",
                profile_name,
                "--min-nodes",
                _GRAPH_WORKER_PROFILE_MIN_NODES,
                "--max-nodes",
                _GRAPH_WORKER_PROFILE_MAX_NODES,
                "-o",
                "none",
            ],
            timeout=900,
        )

    for _ in range(18):
        profile = _az_json_or_none([
            "containerapp",
            "env",
            "workload-profile",
            "show",
            "-g",
            resource_group,
            "-n",
            environment_name,
            "--workload-profile-name",
            profile_name,
        ])
        properties = profile.get("properties", {}) if isinstance(profile, dict) else {}
        if int(properties.get("currentCount") or 0) >= 1:
            return
        time.sleep(10)

    console.print(
        "  [yellow]GraphRAG workload profile is still allocating nodes; "
        "continuing and letting Container Apps wait on create/update.[/yellow]"
    )


def _deployment_failure_context(resource_group: str, name_prefix: str = "") -> str:
    """Collect nested ARM deployment errors for classification and logging."""
    deadline = time.monotonic() + _DEPLOYMENT_CONTEXT_TIMEOUT_SECONDS
    deployment_names = [
        "main",
        "storage",
        "ai-services",
        "search",
        "search-roles",
        "cosmos",
        "container-apps",
        "cosmos-roles",
    ]
    messages: list[str] = []
    for deployment_name in deployment_names:
        remaining = deadline - time.monotonic()
        if remaining <= 0:
            break
        try:
            result = subprocess.run(
                [
                    AZ_COMMAND, "deployment", "operation", "group", "list",
                    "-g", resource_group,
                    "-n", deployment_name,
                    "-o", "json",
                ],
                capture_output=True,
                text=True,
                shell=False,
                timeout=min(_DEPLOYMENT_OPERATION_TIMEOUT_SECONDS, remaining),
            )
        except subprocess.TimeoutExpired:
            log.debug("Timed out collecting deployment operations for %s", deployment_name)
            continue
        if result.returncode != 0 or not result.stdout.strip():
            continue
        try:
            operations = json.loads(result.stdout)
        except json.JSONDecodeError:
            continue
        for operation in operations:
            properties = operation.get("properties", {})
            status = str(properties.get("provisioningState", "")).lower()
            status_message = properties.get("statusMessage", {})
            error = status_message.get("error") if isinstance(status_message, dict) else None
            if status != "failed" and not error:
                continue
            target = properties.get("targetResource", {})
            resource_name = target.get("resourceName") or deployment_name
            if (
                name_prefix
                and deployment_name != "main"
                and not resource_name.startswith(name_prefix)
            ):
                continue
            code = error.get("code") if isinstance(error, dict) else "Failed"
            message = error.get("message") if isinstance(error, dict) else str(status_message)
            messages.append(f"{deployment_name}/{resource_name}: {code}: {message}")
    if not messages:
        return ""
    return "\nNested deployment errors:\n" + "\n".join(messages)


def _deployment_state(resource_group: str, deployment_name: str) -> str:
    try:
        result = subprocess.run(
            [
                AZ_COMMAND, "deployment", "group", "show",
                "-g", resource_group,
                "-n", deployment_name,
                "--query", "properties.provisioningState",
                "-o", "tsv",
            ],
            capture_output=True,
            text=True,
            shell=False,
            timeout=_AZ_CLI_TIMEOUT_SECONDS,
        )
    except subprocess.TimeoutExpired:
        return ""
    if result.returncode != 0:
        return ""
    return result.stdout.strip()


def _cancel_active_deployment(resource_group: str, deployment_name: str = "main") -> None:
    if _deployment_state(resource_group, deployment_name) != "Running":
        return
    console.print(
        f"  [yellow]Deployment '{deployment_name}' is still active; "
        "cancelling before retry.[/yellow]"
    )
    try:
        subprocess.run(
            [
                AZ_COMMAND, "deployment", "group", "cancel",
                "-g", resource_group,
                "-n", deployment_name,
            ],
            capture_output=True,
            text=True,
            shell=False,
            timeout=_AZ_CLI_TIMEOUT_SECONDS,
        )
    except subprocess.TimeoutExpired:
        return
    for _ in range(30):
        state = _deployment_state(resource_group, deployment_name)
        if state != "Running":
            return
        time.sleep(5)


def _deployment_prefix_from_deployment(deployment: dict[str, Any]) -> str:
    parameters = deployment.get("properties", {}).get("parameters", {})
    value = parameters.get("namePrefix", {}).get("value")
    return str(value or "")


def _wait_for_group_deployment(
    resource_group: str,
    deployment_prefix: str,
) -> dict[str, Any]:
    last_state = ""
    for _ in range(_ARM_DEPLOYMENT_MAX_POLLS):
        try:
            deployment = _az_json([
                "deployment", "group", "show", "-g", resource_group, "-n", "main",
            ])
        except RuntimeError as e:
            if "timed out" in str(e).lower():
                time.sleep(_ARM_DEPLOYMENT_POLL_SECONDS)
                continue
            raise
        state = str(deployment.get("properties", {}).get("provisioningState", ""))
        if state != last_state:
            console.print(f"  [dim]ARM deployment state: {state or 'unknown'}[/dim]")
            last_state = state
        if state == "Succeeded":
            return deployment
        if state in {"Failed", "Canceled"}:
            error = deployment.get("properties", {}).get("error")
            active_prefix = _deployment_prefix_from_deployment(deployment) or deployment_prefix
            context = ""
            for _ in range(6):
                context = _deployment_failure_context(resource_group, active_prefix)
                if any(
                    marker in context.lower()
                    for marker in (
                        "serviceunavailable",
                        "high demand",
                        "insufficientresourcesavailable",
                        "customdomaininuse",
                        "storageaccountalreadytaken",
                    )
                ):
                    break
                time.sleep(5)
            raise RuntimeError(
                "az deployment group create -g... failed:\n"
                f"{json.dumps(error) if error else state}"
                f"{context}"
            )
        time.sleep(_ARM_DEPLOYMENT_POLL_SECONDS)

    context = _deployment_failure_context(resource_group, deployment_prefix)
    raise RuntimeError(
        "ARM deployment is still running after the wait window; "
        "leaving it active for Azure to complete."
        f"{context}"
    )


def _deploy_group_template(
    resource_group: str,
    template: Path,
    params_file: Path,
) -> dict[str, Any]:
    """Start a group deployment and poll ARM directly for terminal state.

    `az deployment group create` can stay blocked after a nested deployment has
    already reached Failed. Starting with --no-wait and polling the deployment
    resource ourselves lets the provisioner classify the failure and retry.
    """
    deployment_prefix = _deployment_prefix(params_file)

    if _deployment_state(resource_group, "main") == "Running":
        console.print(
            "  [yellow]Deployment 'main' is already active; waiting for Azure "
            "to finish it.[/yellow]"
        )
        return _wait_for_group_deployment(resource_group, deployment_prefix)

    start_cmd = [
        AZ_COMMAND, "deployment", "group", "create",
        "-g", resource_group,
        "-f", str(template),
        "-p", f"@{params_file}",
        "--no-wait",
        "-o", "json",
    ]
    start = None
    start_timed_out = False
    for _ in range(6):
        try:
            start = subprocess.run(
                start_cmd,
                capture_output=True,
                text=True,
                shell=False,
                timeout=_DEPLOYMENT_START_TIMEOUT_SECONDS,
            )
            start_timed_out = False
        except subprocess.TimeoutExpired:
            start_timed_out = True
            time.sleep(10)
            continue
        if start.returncode == 0 or "DeploymentActive" not in start.stderr:
            break
        console.print(
            "  [yellow]Deployment 'main' is already active; waiting for Azure "
            "to finish it.[/yellow]"
        )
        return _wait_for_group_deployment(resource_group, deployment_prefix)
        time.sleep(10)
    if start is None:
        if _deployment_state(resource_group, "main") == "Running":
            console.print(
                "  [yellow]Deployment 'main' started but the Azure CLI did not "
                "return promptly; waiting for Azure to finish it.[/yellow]"
            )
            return _wait_for_group_deployment(resource_group, deployment_prefix)
        if start_timed_out:
            raise RuntimeError("az deployment group create -g... timed out starting")
        raise RuntimeError("az deployment group create -g... failed to start")
    if start.returncode != 0:
        raise RuntimeError(f"az deployment group create -g... failed:\n{start.stderr.strip()}")

    return _wait_for_group_deployment(resource_group, deployment_prefix)


def _deployment_prefix(params_file: Path) -> str:
    try:
        params = json.loads(params_file.read_text(encoding="utf-8"))
    except (OSError, json.JSONDecodeError):
        return ""
    value = params.get("namePrefix", {}).get("value")
    return str(value or "")


def _search_control_plane_ready(resource_group: str, search_name: str) -> bool:
    try:
        service = _az_json([
            "search", "service", "show",
            "-g", resource_group,
            "-n", search_name,
        ])
    except Exception as exc:
        log.debug("Search control-plane readiness check failed: %s", exc)
        return False
    provisioning_state = str(service.get("provisioningState", "")).lower()
    status = str(service.get("status", "")).lower()
    return provisioning_state == "succeeded" and status in {"", "running"}


def _check_az_cli():
    """Verify az CLI is installed and user is logged in."""
    try:
        result = subprocess.run(
            [AZ_COMMAND, "account", "show", "-o", "json"],
            capture_output=True,
            text=True,
            shell=False,
            timeout=_AZ_CLI_TIMEOUT_SECONDS,
        )
    except FileNotFoundError:
        console.print("[red]Azure CLI (az) not found. Install: https://aka.ms/installazurecli[/red]")
        raise SystemExit(1)
    except subprocess.TimeoutExpired:
        console.print("[red]Azure CLI account check timed out. Run: az account show[/red]")
        raise SystemExit(1)
    if result.returncode != 0:
        console.print("[red]Not logged in to Azure CLI. Run: az login[/red]")
        raise SystemExit(1)
    account = json.loads(result.stdout)
    console.print(f"  Azure subscription: [cyan]{account.get('name', 'unknown')}[/cyan]")


def _resolve_deployer_object_id(configured_oid: str = "") -> tuple[str, str]:
    """Resolve the deployer object ID for RBAC assignment.

    Prefer an explicitly configured value. Otherwise try Graph-backed lookup via
    `az ad signed-in-user show`, then fall back to decoding the current ARM token
    and reading the `oid` claim. The ARM token path avoids Graph failures caused
    by Conditional Access / CAE challenges.
    """
    if configured_oid:
        return configured_oid, "configured"

    try:
        result = subprocess.run(
            [AZ_COMMAND, "ad", "signed-in-user", "show", "--query", "id", "-o", "tsv"],
            capture_output=True,
            text=True,
            shell=False,
            timeout=_AZ_CLI_TIMEOUT_SECONDS,
        )
    except subprocess.TimeoutExpired:
        result = None
    if result and result.returncode == 0 and result.stdout.strip():
        return result.stdout.strip(), "azure-ad"

    try:
        token_result = subprocess.run(
            [
                AZ_COMMAND, "account", "get-access-token",
                "--resource", "https://management.azure.com/",
                "--query", "accessToken",
                "-o", "tsv",
            ],
            capture_output=True,
            text=True,
            shell=False,
            timeout=_AZ_CLI_TIMEOUT_SECONDS,
        )
    except subprocess.TimeoutExpired:
        return "", ""
    if token_result.returncode != 0 or not token_result.stdout.strip():
        return "", ""

    try:
        token = token_result.stdout.strip()
        payload = token.split(".")[1]
        payload += "=" * (-len(payload) % 4)
        claims = json.loads(base64.urlsafe_b64decode(payload).decode("utf-8"))
        oid = str(claims.get("oid", "")).strip()
        if oid:
            return oid, "arm-token"
    except Exception as exc:
        log.debug("Failed to decode ARM token for deployer OID: %s", exc)

    return "", ""


def provision_architectures(cfg: RetrieveConfig):
    """Provision Azure resources for all selected architectures.

    Uses a single Bicep deployment that provisions shared resources
    (Storage, AI Foundry, Search) plus architecture-specific config.
    """
    if not cfg.azure.resource_group:
        raise ValueError(
            "No resource_group set in retrieve.yaml. Set azure.resource_group before provisioning."
        )

    console.print("\n[bold]Azure Provisioning[/bold]\n")
    with step("provision.check_az_cli"):
        _check_az_cli()

    db = RetrieveDB(cfg.db_path)
    arch_names = cfg.architectures
    unknown = [a for a in arch_names if a not in ARCHITECTURES]
    if unknown:
        console.print(f"[red]Unknown architectures: {unknown}[/red]")
        return

    # Prefer US regions that aren't called out in Azure AI Search regional
    # capacity-constraint guidance. Any regional capacity failure moves the full
    # deployment together; we don't split individual services across regions.
    location = cfg.azure.location
    DEPLOYMENT_FALLBACK_REGIONS = ["southcentralus", "centralus", "westus3", "northcentralus"]
    deployment_regions = _ordered_regions(location, DEPLOYMENT_FALLBACK_REGIONS)
    attempted_deployment_regions: set[str] = set()

    console.print(f"  Resource group:   [cyan]{cfg.azure.resource_group}[/cyan]")
    console.print(f"  Location:         [cyan]{location}[/cyan]")
    console.print(f"  Name prefix:      [cyan]{cfg.azure.name_prefix}[/cyan]")
    console.print(f"  Architectures:    [cyan]{', '.join(arch_names)}[/cyan]\n")

    # Resolve deployer object ID for RBAC if not explicitly configured.
    deployer_oid, deployer_oid_source = _resolve_deployer_object_id(cfg.azure.deployer_object_id)
    if deployer_oid:
        if deployer_oid_source == "configured":
            console.print(f"  Deployer OID:     [cyan]{deployer_oid}[/cyan]")
        elif deployer_oid_source == "azure-ad":
            console.print(f"  Deployer OID:     [cyan]{deployer_oid}[/cyan] (auto-detected)")
        else:
            console.print(f"  Deployer OID:     [cyan]{deployer_oid}[/cyan] (ARM token fallback)")
    else:
        console.print(
            "  [yellow]Deployer OID could not be resolved; blob upload may fail "
            "unless azure.deployer_object_id is set.[/yellow]"
        )

    # Check for already-provisioned architectures
    for name in arch_names:
        existing = db.get_architecture(name)
        if existing and existing["status"] == "provisioned":
            console.print(f"  [dim]{name}: already provisioned, skipping[/dim]")
            arch_names = [a for a in arch_names if a != name]

    if not arch_names:
        console.print("[green]All architectures already provisioned.[/green]")
        return

    # Ensure resource group exists. A deleting resource group is a soft gate:
    # keep the deployment moving by generating a sibling RG name and telling the
    # user which boundary is actually being used.
    requested_resource_group = cfg.azure.resource_group
    console.print("  Creating resource group (if needed)...")
    with step("provision.create_resource_group"):
        last_error: RuntimeError | None = None
        for candidate_rg in candidate_resource_group_names(requested_resource_group):
            try:
                _az_json([
                    "group", "create",
                    "-n", candidate_rg,
                    "-l", cfg.azure.location,
                ])
                cfg.azure.resource_group = candidate_rg
                if candidate_rg != requested_resource_group:
                    console.print(
                        f"  [yellow]Resource group '{requested_resource_group}' is being "
                        f"deleted; continuing with '{candidate_rg}'.[/yellow]"
                    )
                    emit_progress(
                        f"Using generated resource group '{candidate_rg}'",
                        stage="provision.rg",
                        requested_resource_group=requested_resource_group,
                        effective_resource_group=candidate_rg,
                    )
                break
            except RuntimeError as e:
                if _is_resource_group_deleting_error(e):
                    last_error = e
                    continue
                if _is_existing_resource_group_location_error(e):
                    _az_json(["group", "show", "-n", candidate_rg])
                    cfg.azure.resource_group = candidate_rg
                    break
                console.print(f"[red]Failed to create resource group: {e}[/red]")
                emit_error("Failed to create resource group", e, stage="provision.rg")
                raise
        else:
            error = last_error or RuntimeError("No resource group name candidates available")
            console.print(f"[red]Failed to create resource group: {error}[/red]")
            emit_error("Failed to create resource group", error, stage="provision.rg")
            raise error

    # Resolve globally unique names before Bicep preflight. This is the single
    # gate for Storage, AI Services, Search, Cosmos, and the RG-scoped
    # Container Apps names derived from the chosen prefix.
    requested_name_prefix = cfg.azure.name_prefix
    blocked_name_prefixes: set[str] = set()
    current_deploy_location = cfg.azure.location
    console.print("  Resolving Azure resource names...")
    with step("provision.resolve_names"):
        try:
            deployment_names = resolve_deployment_names(
                requested_name_prefix,
                cfg.azure.resource_group,
                current_deploy_location,
                arch_names,
                blocked_prefixes=blocked_name_prefixes,
            )
        except RuntimeError as e:
            console.print(f"[red]Failed to resolve Azure resource names: {e}[/red]")
            emit_error("Failed to resolve Azure resource names", e, stage="provision.resolve_names")
            raise

    effective_name_prefix = deployment_names.name_prefix
    if effective_name_prefix != cfg.azure.name_prefix:
        requested_name_prefix = cfg.azure.name_prefix
        cfg.azure.name_prefix = effective_name_prefix
        console.print(
            f"  [yellow]Name prefix '{requested_name_prefix}' is unavailable; "
            f"using '{effective_name_prefix}' for this deployment.[/yellow]"
        )
        emit_progress(
            f"Using generated name prefix '{effective_name_prefix}'",
            stage="provision.resolve_names",
            requested_prefix=requested_name_prefix,
            effective_prefix=effective_name_prefix,
        )

    # Wait for search service to finish deleting (if still in progress from earlier run)
    search_name = deployment_names.search_service
    console.print(f"  Checking if search service '{search_name}' is still deleting...")
    with step("provision.wait_search_delete"):
        for attempt in range(30):  # up to 5 min
            try:
                result = subprocess.run(
                    [
                        AZ_COMMAND, "search", "service", "show",
                        "-g", cfg.azure.resource_group,
                        "-n", search_name,
                        "-o", "json",
                    ],
                    capture_output=True,
                    text=True,
                    shell=False,
                    timeout=_AZ_CLI_TIMEOUT_SECONDS,
                )
            except subprocess.TimeoutExpired:
                break
            if result.returncode != 0:
                # Service doesn't exist or RG doesn't exist — good to proceed
                break
            try:
                svc = json.loads(result.stdout)
                status = svc.get("provisioningState", "")
                if status.lower() == "deleting":
                    console.print(
                        "  [yellow]Search service still deleting "
                        f"(attempt {attempt + 1}/30), waiting 10s...[/yellow]"
                    )
                    emit_progress(
                        f"Search service still deleting (attempt {attempt + 1}/30)",
                        stage="provision.wait_search_delete",
                    )
                    time.sleep(10)
                    continue
                else:
                    # Exists but not deleting — allow the idempotent redeploy to
                    # proceed. If its region conflicts with the requested full-stack
                    # location, ARM will return InvalidResourceLocation and the
                    # name-prefix retry path will generate a fresh boundary.
                    break
            except json.JSONDecodeError:
                break
        else:
            console.print(
                "  [yellow]Search service still deleting after 5 min — "
                "proceeding anyway[/yellow]"
            )

    # Deploy main Bicep template
    main_bicep = BICEP_DIR / "main.bicep"
    if not main_bicep.exists():
        console.print(f"[red]Bicep template not found: {main_bicep}[/red]")
        return

    console.print("\n  [bold]Deploying Azure resources...[/bold]")
    console.print("  (This may take 3-5 minutes)\n")
    emit_progress("Starting Bicep deployment", stage="provision.deploy")

    with step("provision.deploy_bicep"):
        try:
            # Write parameters to a temp JSON file to avoid PowerShell quote-stripping
            # on array/object values (Windows PS strips inline JSON quotes).
            import tempfile

            def _deploy_bicep(
                deploy_location: str,
                search_location: str | None = None,
            ) -> dict[str, Any]:
                params_dict = {
                    "namePrefix": {"value": effective_name_prefix},
                    "location": {"value": deploy_location},
                    "architectures": {"value": arch_names},
                }
                if search_location:
                    params_dict["searchLocation"] = {"value": search_location}
                if deployer_oid:
                    params_dict["deployerObjectId"] = {"value": deployer_oid}

                params_file = Path(tempfile.gettempdir()) / "retrieve-params.json"
                params_file.write_text(json.dumps(params_dict), encoding="utf-8")

                return _deploy_group_template(cfg.azure.resource_group, main_bicep, params_file)

            def _deploy_with_current_names() -> dict[str, Any]:
                try:
                    return _deploy_bicep(
                        current_deploy_location,
                        search_location=current_deploy_location,
                    )
                except RuntimeError as e:
                    err_str = str(e)
                    if "InvalidResourceLocation" in err_str:
                        raise
                    if "ServiceDeleting" in err_str:
                        console.print(
                            "\n  [yellow]Search service still deleting — waiting 60s "
                            "and retrying...[/yellow]"
                        )
                        time.sleep(60)
                        return _deploy_bicep(current_deploy_location)
                    raise

            for deploy_attempt in range(8):
                try:
                    result = _deploy_with_current_names()
                    break
                except RuntimeError as e:
                    if _is_regional_capacity_error(e):
                        failed_region = current_deploy_location
                        attempted_deployment_regions.add(failed_region)
                        next_region = next(
                            (
                                region
                                for region in deployment_regions
                                if region not in attempted_deployment_regions
                            ),
                            "",
                        )
                        if not next_region or deploy_attempt == 7:
                            raise

                        blocked_name_prefixes.add(effective_name_prefix)
                        current_deploy_location = next_region
                        cfg.azure.location = current_deploy_location
                        deployment_names = resolve_deployment_names(
                            requested_name_prefix,
                            cfg.azure.resource_group,
                            current_deploy_location,
                            arch_names,
                            blocked_prefixes=blocked_name_prefixes,
                        )
                        effective_name_prefix = deployment_names.name_prefix
                        cfg.azure.name_prefix = effective_name_prefix
                        search_name = deployment_names.search_service
                        console.print(
                            f"  [yellow]Regional capacity failed in "
                            f"{failed_region}; retrying the "
                            f"whole deployment in {current_deploy_location} with prefix "
                            f"'{effective_name_prefix}'.[/yellow]"
                        )
                        emit_progress(
                            f"Retrying full deployment in {current_deploy_location}",
                            stage="provision.deploy",
                            effective_location=current_deploy_location,
                            effective_prefix=effective_name_prefix,
                        )
                        continue

                    if not is_name_collision_error(str(e)) or deploy_attempt == 7:
                        raise
                    blocked_name_prefixes.add(effective_name_prefix)
                    deployment_names = resolve_deployment_names(
                        requested_name_prefix,
                        cfg.azure.resource_group,
                        current_deploy_location,
                        arch_names,
                        blocked_prefixes=blocked_name_prefixes,
                    )
                    effective_name_prefix = deployment_names.name_prefix
                    cfg.azure.name_prefix = effective_name_prefix
                    search_name = deployment_names.search_service
                    console.print(
                        f"  [yellow]ARM rejected prefix due to a name collision; "
                        f"retrying with '{effective_name_prefix}'.[/yellow]"
                    )
            else:
                raise RuntimeError("Bicep deployment did not produce a result.")
        except RuntimeError as e:
            console.print(f"[red]Deployment failed: {e}[/red]")
            emit_error("Bicep deployment failed", e, stage="provision.deploy")
            raise

    deployed_name_prefix = _deployment_prefix_from_deployment(result)
    if deployed_name_prefix and deployed_name_prefix != effective_name_prefix:
        console.print(
            f"  [yellow]Attached to active deployment with prefix "
            f"'{deployed_name_prefix}'.[/yellow]"
        )
        effective_name_prefix = deployed_name_prefix
        cfg.azure.name_prefix = deployed_name_prefix
        deployment_names = build_deployment_names(deployed_name_prefix)
        search_name = deployment_names.search_service

    # Extract outputs
    outputs = result.get("properties", {}).get("outputs", {})
    search_endpoint = outputs.get("searchEndpoint", {}).get("value", "")
    search_service_id = outputs.get("searchServiceId", {}).get("value", "")
    storage_name = outputs.get("storageAccountName", {}).get("value", "")
    storage_account_id = outputs.get("storageAccountId", {}).get("value", "")
    ai_endpoint = outputs.get("aiServicesEndpoint", {}).get("value", "")
    ai_services_id = outputs.get("aiServicesId", {}).get("value", "")
    cosmos_endpoint = outputs.get("cosmosEndpoint", {}).get("value", "")
    cosmos_name = outputs.get("cosmosAccountName", {}).get("value", "")
    aca_endpoint = outputs.get("containerAppEndpoint", {}).get("value", "")
    aca_name = outputs.get("containerAppName", {}).get("value", "")
    graph_worker_name = outputs.get("graphWorkerAppName", {}).get("value", "")
    graph_worker_env_name = deployment_names.graph_worker_environment
    graph_worker_endpoint = ""

    if "graphrag" in arch_names:
        graph_worker_endpoint, _ = _deploy_graphrag_worker_container(
            resource_group=cfg.azure.resource_group,
            location=current_deploy_location,
            environment_name=graph_worker_env_name,
            app_name=graph_worker_name or deployment_names.graph_worker_app,
            storage_account=storage_name,
            storage_account_id=storage_account_id,
            ai_services_endpoint=ai_endpoint,
            ai_services_id=ai_services_id,
            search_endpoint=search_endpoint,
            search_service_id=search_service_id,
            cosmos_account=cosmos_name,
            embedding_model="text-embedding-3-large",
        )

    if cosmos_name and deployer_oid:
        _assign_cosmos_sql_role(
            cfg.azure.resource_group,
            cosmos_name,
            deployer_oid,
            _COSMOS_SQL_DATA_READER_ROLE_ID,
            "Cosmos DB Built-in Data Reader to deployer",
        )

    console.print("[bold green]Deployment complete![/bold green]\n")
    emit_progress(
        "Bicep deployment complete",
        stage="provision.deploy",
        search_endpoint=search_endpoint,
        storage_account=storage_name,
    )
    console.print(f"  Search endpoint:  [cyan]{search_endpoint}[/cyan]")
    console.print(f"  Storage account:  [cyan]{storage_name}[/cyan]")
    if ai_endpoint:
        console.print(f"  AI Foundry:       [cyan]{ai_endpoint}[/cyan]")
    if cosmos_endpoint:
        console.print(f"  Cosmos DB:        [cyan]{cosmos_endpoint}[/cyan]")
    if graph_worker_endpoint:
        console.print(f"  GraphRAG worker:  [cyan]{graph_worker_endpoint}[/cyan]")
    if aca_endpoint:
        console.print(f"  Container Apps:   [cyan]{aca_endpoint}[/cyan]")

    # Register architectures in SQLite
    with step("provision.register_architectures"):
        for name in arch_names:
            arch_config = {
                "search_endpoint": search_endpoint,
                "storage_account": storage_name,
                "ai_services_endpoint": ai_endpoint,
                "resource_group": cfg.azure.resource_group,
                "index_name": f"{effective_name_prefix}-{name}",
            }
            # Add architecture-specific endpoints
            if name == "graphrag":
                arch_config["cosmos_endpoint"] = cosmos_endpoint
                arch_config["cosmos_account"] = cosmos_name
                arch_config["graph_worker_endpoint"] = graph_worker_endpoint
                arch_config["graph_worker_app"] = (
                    graph_worker_name or deployment_names.graph_worker_app
                )
                arch_config["graph_worker_environment"] = graph_worker_env_name
                arch_config["graph_worker_workload_profile"] = _GRAPH_WORKER_PROFILE_NAME
            elif name == "lightrag":
                arch_config["container_app_endpoint"] = aca_endpoint
                arch_config["container_app"] = aca_name
            db.register_architecture(name, arch_config)
            # Update status to provisioned
            db.conn.execute(
                "UPDATE architectures SET status = 'provisioned', resources_provisioned = ? "
                "WHERE name = ? AND status = 'registered'",
                (json.dumps(arch_config), name),
            )
            db.conn.commit()
            console.print(f"  [green]✓ {name}[/green] registered")
            emit_progress(f"Registered {name}", stage="provision.register", architecture=name)

    # Wait for search service to be network-accessible (Basic SKU can take 2-10 min)
    if search_endpoint:
        console.print("\n  Waiting for search service to be reachable...")
        with step("provision.wait_search_reachable"):
            if search_name and _search_control_plane_ready(cfg.azure.resource_group, search_name):
                console.print("  [green]Search service running in Azure[/green]")
                emit_progress(
                    "Search service running in Azure",
                    stage="provision.wait_search_reachable",
                )
            else:
                for attempt in range(6):
                    try:
                        http_requests.get(search_endpoint, timeout=(5, 10))
                        console.print(
                            f"  [green]Search service reachable (attempt {attempt + 1})[/green]"
                        )
                        emit_progress(
                            f"Search service reachable (attempt {attempt + 1})",
                            stage="provision.wait_search_reachable",
                        )
                        break
                    except Exception:
                        if attempt < 5:
                            emit_progress(
                                f"Search service not reachable yet (attempt {attempt + 1}/6)",
                                stage="provision.wait_search_reachable",
                            )
                            time.sleep(10)
                        else:
                            console.print(
                                "  [yellow]Search data plane did not respond to the local "
                                "probe yet, but Azure reports the service is provisioned.[/yellow]"
                            )

    console.print("\n  [dim]Next step: retrieve index[/dim]\n")
    db.close()
