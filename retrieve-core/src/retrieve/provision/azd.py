"""Capacity-aware Azure Developer CLI lifecycle for Retrieve."""

from __future__ import annotations

import json
import os
import subprocess
from dataclasses import asdict, dataclass
from pathlib import Path
from typing import Any
from urllib.parse import urlencode

import requests

from retrieve.cli_process import resolve_cli_command
from retrieve.config import RetrieveConfig, load_config
from retrieve.db import RetrieveDB
from retrieve.observability import emit_progress

REGION_CANDIDATES = (
    "northcentralus",
    "westus3",
    "centralus",
    "southcentralus",
    "eastus2",
    "swedencentral",
)
_REQUIRED_PROVIDERS = (
    "Microsoft.App",
    "Microsoft.ContainerRegistry",
    "Microsoft.CognitiveServices",
    "Microsoft.Insights",
    "Microsoft.ManagedIdentity",
    "Microsoft.OperationalInsights",
    "Microsoft.Search",
    "Microsoft.Storage",
)
_CAPACITY_MARKERS = (
    "allocationfailed",
    "capacity is unavailable",
    "capacity unavailable",
    "insufficient capacity",
    "insufficientcapacity",
    "outofcapacity",
    "regional capacity",
    "service unavailable in this region",
    "temporarily unavailable in this region",
)
_QUOTA_MARKERS = (
    "quotaexceeded",
    "quota exceeded",
    "exceeding approved quota",
    "operation could not be completed as it results in exceeding",
)
_PROJECT_ROOT = Path(__file__).resolve().parents[4]


@dataclass(frozen=True)
class RegionCapacityAssessment:
    region: str
    search_sku: str
    search_current: int
    search_limit: int
    chat_model: str
    chat_version: str
    chat_sku: str
    chat_requested_capacity: int
    chat_available_capacity: int
    embedding_model: str
    embedding_version: str
    embedding_sku: str
    embedding_requested_capacity: int
    embedding_available_capacity: int

    def to_dict(self) -> dict[str, Any]:
        return asdict(self)


class RegionUnavailableError(RuntimeError):
    """Raised when a region fails a catalog, quota, or capacity gate."""


def _run(
    command: list[str],
    *,
    check: bool = True,
    env: dict[str, str] | None = None,
) -> subprocess.CompletedProcess[str]:
    return subprocess.run(
        resolve_cli_command(command),
        cwd=_PROJECT_ROOT,
        env=env,
        check=check,
        capture_output=True,
        text=True,
    )


def _json_command(command: list[str]) -> Any:
    result = _run([*command, "--output", "json"])
    return json.loads(result.stdout or "null")


def _azd_value(name: str) -> str:
    result = _run(["azd", "env", "get-value", name], check=False)
    return result.stdout.strip() if result.returncode == 0 else ""


def _set_azd_value(name: str, value: str) -> None:
    _run(["azd", "env", "set", name, value])


def _private_corpus_is_attested(environment_name: str, subscription_id: str) -> bool:
    attested_creation = _azd_value("RETRIEVE_CORPUS_STORAGE_CREATED_AT")
    storage_account = _azd_value("AZURE_STORAGE_ACCOUNT_NAME")
    if not attested_creation or not storage_account:
        return False
    result = _run(
        [
            "az",
            "storage",
            "account",
            "show",
            "--subscription",
            subscription_id,
            "--resource-group",
            _isolated_resource_group(environment_name),
            "--name",
            storage_account,
            "--query",
            "creationTime",
            "--output",
            "tsv",
        ],
        check=False,
    )
    return result.returncode == 0 and result.stdout.strip() == attested_creation


def _cleanup_temporary_graph_runtime(
    cfg: RetrieveConfig,
    *,
    environment_name: str,
    subscription_id: str,
    region: str,
) -> None:
    from retrieve.provision.teardown import _delete_graph_runtime

    resource_token = _azd_value("AZURE_RESOURCE_TOKEN") or cfg.azure.name_prefix
    _delete_graph_runtime(
        {
            "resource_group": _isolated_resource_group(environment_name),
            "subscription_id": subscription_id,
            "resource_token": resource_token,
            "location": region,
            "graph_job_name": _azd_value("AZURE_GRAPHRAG_JOB_NAME"),
            "graph_worker_environment": _azd_value(
                "AZURE_CONTAINER_APPS_ENVIRONMENT_NAME"
            ),
        }
    )
    _set_azd_value("AZURE_DEPLOY_GRAPH_RUNTIME", "false")


def _purge_matching_soft_deleted_ai_account(
    environment_name: str,
    subscription_id: str,
    region: str,
) -> None:
    account_name = _azd_value("AZURE_AI_SERVICES_NAME")
    if not account_name:
        return
    resource_group = _isolated_resource_group(environment_name)
    result = _run(
        [
            "az",
            "cognitiveservices",
            "account",
            "list-deleted",
            "--subscription",
            subscription_id,
            "--output",
            "json",
        ]
    )
    deleted = json.loads(result.stdout or "[]")
    expected_suffix = (
        f"/resourcegroups/{resource_group}/deletedaccounts/{account_name}"
    ).lower()
    matches = [
        account
        for account in deleted
        if str(account.get("name") or "") == account_name
        and str(account.get("location") or "").lower() == region.lower()
        and str(account.get("id") or "").lower().endswith(expected_suffix)
    ]
    if not matches:
        return
    if len(matches) != 1:
        raise RuntimeError("Multiple matching soft-deleted AI Services accounts found")
    _run(
        [
            "az",
            "cognitiveservices",
            "account",
            "purge",
            "--subscription",
            subscription_id,
            "--location",
            region,
            "--resource-group",
            resource_group,
            "--name",
            account_name,
        ]
    )


def _arm_get(path: str, query: dict[str, str] | None = None) -> dict[str, Any]:
    token_result = _json_command(
        ["az", "account", "get-access-token", "--resource", "https://management.azure.com/"]
    )
    token = str(token_result.get("accessToken") or "")
    if not token:
        raise RuntimeError("Azure CLI did not return an ARM access token")
    url = f"https://management.azure.com{path}"
    if query:
        url = f"{url}?{urlencode(query)}"
    response = requests.get(
        url,
        headers={"Authorization": f"Bearer {token}"},
        timeout=(10, 60),
    )
    response.raise_for_status()
    payload = response.json()
    if not isinstance(payload, dict):
        raise RuntimeError("Azure management API returned a non-object response")
    return payload


def _validate_provider_registrations(subscription_id: str) -> None:
    for namespace in _REQUIRED_PROVIDERS:
        provider = _json_command(
            [
                "az",
                "provider",
                "show",
                "--subscription",
                subscription_id,
                "--namespace",
                namespace,
            ]
        )
        state = str(provider.get("registrationState") or "")
        if state.lower() != "registered":
            raise RuntimeError(f"Azure resource provider {namespace} is not registered")


def _search_usage(subscription_id: str, region: str, sku: str) -> tuple[int, int]:
    payload = _arm_get(
        f"/subscriptions/{subscription_id}/providers/Microsoft.Search/locations/{region}/usages",
        {"api-version": "2025-05-01"},
    )
    for usage in payload.get("value", []):
        name = usage.get("name") or {}
        if str(name.get("value") or "").lower() == sku.lower():
            return int(usage.get("currentValue") or 0), int(usage.get("limit") or 0)
    raise RegionUnavailableError(f"Azure AI Search SKU {sku} is not offered in {region}")


def _model_capacity(
    subscription_id: str,
    region: str,
    *,
    model_name: str,
    model_version: str,
    sku: str,
) -> int:
    payload = _arm_get(
        f"/subscriptions/{subscription_id}/providers/Microsoft.CognitiveServices/locations/{region}/modelCapacities",
        {
            "api-version": "2024-10-01",
            "modelFormat": "OpenAI",
            "modelName": model_name,
            "modelVersion": model_version,
        },
    )
    for capacity in payload.get("value", []):
        if str(capacity.get("name") or "").lower() == sku.lower():
            return int((capacity.get("properties") or {}).get("availableCapacity") or 0)
    raise RegionUnavailableError(
        f"{model_name} {model_version} with {sku} is not offered in {region}"
    )


def assess_region_capacity(
    subscription_id: str,
    region: str,
    *,
    search_sku: str = "basic",
    chat_model: str = "gpt-4.1",
    chat_version: str = "2025-04-14",
    chat_sku: str = "GlobalStandard",
    chat_capacity: int = 10,
    embedding_model: str = "text-embedding-3-large",
    embedding_version: str = "1",
    embedding_sku: str = "GlobalStandard",
    embedding_capacity: int = 100,
) -> RegionCapacityAssessment:
    """Assess catalog, quota, and documented model capacity for one region."""
    search_current, search_limit = _search_usage(subscription_id, region, search_sku)
    if search_limit - search_current < 1:
        raise RegionUnavailableError(
            f"Azure AI Search {search_sku} quota is exhausted in {region} "
            f"({search_current}/{search_limit})"
        )
    chat_available = _model_capacity(
        subscription_id,
        region,
        model_name=chat_model,
        model_version=chat_version,
        sku=chat_sku,
    )
    if chat_available < chat_capacity:
        raise RegionUnavailableError(
            f"{chat_model} {chat_sku} capacity in {region} is {chat_available}; "
            f"{chat_capacity} is required"
        )
    embedding_available = _model_capacity(
        subscription_id,
        region,
        model_name=embedding_model,
        model_version=embedding_version,
        sku=embedding_sku,
    )
    if embedding_available < embedding_capacity:
        raise RegionUnavailableError(
            f"{embedding_model} {embedding_sku} capacity in {region} is "
            f"{embedding_available}; {embedding_capacity} is required"
        )
    return RegionCapacityAssessment(
        region=region,
        search_sku=search_sku,
        search_current=search_current,
        search_limit=search_limit,
        chat_model=chat_model,
        chat_version=chat_version,
        chat_sku=chat_sku,
        chat_requested_capacity=chat_capacity,
        chat_available_capacity=chat_available,
        embedding_model=embedding_model,
        embedding_version=embedding_version,
        embedding_sku=embedding_sku,
        embedding_requested_capacity=embedding_capacity,
        embedding_available_capacity=embedding_available,
    )


def classify_deployment_failure(output: str) -> str:
    normalized = output.lower().replace("_", "")
    if any(marker.replace("_", "") in normalized for marker in _QUOTA_MARKERS):
        return "quota"
    if any(marker.replace("_", "") in normalized for marker in _CAPACITY_MARKERS):
        return "capacity"
    return "fatal"


def _isolated_resource_group(environment_name: str) -> str:
    if not environment_name or environment_name.lower() in {"dev", "test", "prod", "production"}:
        raise RuntimeError("A unique azd environment name is required")
    resource_group = f"rg-{environment_name}"
    protected = {
        value.strip().lower()
        for value in os.environ.get("RETRIEVE_PROTECTED_RESOURCE_GROUPS", "").split(",")
        if value.strip()
    }
    if resource_group.lower() in protected:
        raise RuntimeError(f"Refusing to mutate protected resource group {resource_group}")
    return resource_group


def _cleanup_failed_attempt(environment_name: str, subscription_id: str) -> None:
    resource_group = _isolated_resource_group(environment_name)
    exists = (
        _run(
            [
                "az",
                "group",
                "exists",
                "--subscription",
                subscription_id,
                "--name",
                resource_group,
            ]
        )
        .stdout.strip()
        .lower()
    )
    if exists != "true":
        return
    cleanup = _run(
        [
            "azd",
            "down",
            "--environment",
            environment_name,
            "--purge",
            "--force",
            "--no-prompt",
        ],
        check=False,
    )
    if cleanup.returncode != 0:
        details = (cleanup.stderr or cleanup.stdout).strip()
        raise RuntimeError(f"Failed to clean isolated regional deployment attempt: {details}")


def _selected_architectures(
    cfg: RetrieveConfig,
    config_path: str | Path,
) -> list[str]:
    config_target = Path(config_path).resolve()
    db_path = Path(cfg.db_path)
    if not db_path.is_absolute():
        db_path = config_target.parent / db_path
    db = RetrieveDB(db_path)
    try:
        session = db.get_generation_preferences("ui_session") or {}
    finally:
        db.close()
    selected = session.get("selected_architectures")
    if isinstance(selected, list) and selected:
        return [str(name) for name in selected if str(name).strip()]
    return list(cfg.architectures)


def provision_architectures(
    cfg: RetrieveConfig,
    *,
    config_path: str | Path = "retrieve.yaml",
) -> dict[str, Any]:
    """Provision Retrieve dependencies with bounded whole-stack regional fallback."""
    environment_name = _azd_value("AZURE_ENV_NAME")
    _isolated_resource_group(environment_name)
    subscription_id = _azd_value("AZURE_SUBSCRIPTION_ID") or cfg.azure.subscription_id
    if not subscription_id:
        raise RuntimeError("AZURE_SUBSCRIPTION_ID is not configured in the azd environment")
    _validate_provider_registrations(subscription_id)

    persisted_region = _azd_value("RETRIEVE_DEPLOYMENT_REGION") or _azd_value("AZURE_LOCATION")
    regions = [persisted_region] if persisted_region in REGION_CANDIDATES else []
    regions.extend(region for region in REGION_CANDIDATES if region not in regions)
    search_sku = _azd_value("AZURE_SEARCH_SKU") or "basic"
    chat_capacity = int(_azd_value("AZURE_OPENAI_CHAT_CAPACITY") or 10)
    embedding_capacity = int(_azd_value("AZURE_OPENAI_EMBEDDING_CAPACITY") or 100)
    config_target = Path(config_path).resolve()
    cfg.architectures = _selected_architectures(cfg, config_target)
    graph_runtime_required = "graphrag" in cfg.architectures
    seed_runtime_only = not graph_runtime_required and not _private_corpus_is_attested(
        environment_name, subscription_id
    )
    _set_azd_value(
        "AZURE_DEPLOY_GRAPH_RUNTIME",
        "true" if graph_runtime_required or seed_runtime_only else "false",
    )
    command_env = os.environ.copy()
    command_env.update(
        {
            "RETRIEVE_CONFIG_PATH": str(config_target),
            "RETRIEVE_CORPUS_DIR": str(Path(cfg.corpus.output_dir).resolve()),
            "RETRIEVE_ARCHITECTURES": ",".join(cfg.architectures),
            "RETRIEVE_NON_INTERACTIVE": "true",
        }
    )

    failures: list[str] = []
    for region in regions:
        try:
            assessment = assess_region_capacity(
                subscription_id,
                region,
                search_sku=search_sku,
                chat_capacity=chat_capacity,
                embedding_capacity=embedding_capacity,
            )
        except RegionUnavailableError as exc:
            failures.append(f"{region}: {exc}")
            emit_progress(
                f"Skipping {region}: {exc}",
                stage="provision.capacity",
                region=region,
                status="unavailable",
            )
            continue

        _set_azd_value("AZURE_LOCATION", region)
        _set_azd_value("RETRIEVE_DEPLOYMENT_REGION", region)
        _purge_matching_soft_deleted_ai_account(
            environment_name,
            subscription_id,
            region,
        )
        emit_progress(
            f"Azure capacity preflight passed in {region}",
            stage="provision.capacity",
            **assessment.to_dict(),
        )
        preview = _run(
            ["azd", "provision", "--preview", "--no-prompt"],
            check=False,
            env=command_env,
        )
        if preview.returncode != 0:
            details = (preview.stderr or preview.stdout).strip()
            raise RuntimeError(f"azd provisioning preview failed in {region}: {details}")

        deployment = _run(
            ["azd", "provision", "--no-prompt"],
            check=False,
            env=command_env,
        )
        if deployment.returncode == 0:
            refreshed = load_config(config_target)
            cfg.azure = refreshed.azure
            cfg.architectures = refreshed.architectures
            if seed_runtime_only:
                _cleanup_temporary_graph_runtime(
                    cfg,
                    environment_name=environment_name,
                    subscription_id=subscription_id,
                    region=region,
                )
            return {
                "status": "provisioned",
                "environment": environment_name,
                "region": region,
                "capacity": assessment.to_dict(),
            }

        details = "\n".join(part for part in (deployment.stdout, deployment.stderr) if part).strip()
        failure_kind = classify_deployment_failure(details)
        failures.append(f"{region}: {failure_kind}: {details[-2_000:]}")
        if failure_kind != "capacity":
            raise RuntimeError(f"Azure deployment failed in {region} ({failure_kind}): {details}")
        emit_progress(
            f"Azure reported backend capacity exhaustion in {region}; cleaning the "
            "isolated attempt before trying the next whole-stack region",
            stage="provision.capacity",
            region=region,
            status="retrying",
        )
        _cleanup_failed_attempt(environment_name, subscription_id)

    raise RegionUnavailableError(
        "No candidate region passed Retrieve capacity/deployment gates: " + " | ".join(failures)
    )
