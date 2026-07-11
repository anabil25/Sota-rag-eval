"""Central Azure resource name guard for provision deployments."""

from __future__ import annotations

import json
import logging
import random
import re
import shutil
import string
import subprocess
from dataclasses import dataclass
from typing import Any

import requests

log = logging.getLogger(__name__)
AZ_COMMAND = shutil.which("az.cmd") or shutil.which("az") or "az"

# Bicep derives the storage account as `${namePrefix}store`; storage account
# names are the tightest global constraint at 24 chars and lowercase alnum only.
_MAX_PREFIX_FOR_DERIVED_NAMES = 24 - len("store")
_MAX_RESOURCE_GROUP_NAME_LENGTH = 90
_SUFFIX_LENGTH = 4
_AZ_CLI_TIMEOUT_SECONDS = 45


@dataclass(frozen=True)
class DeploymentNames:
    """All resource names derived from a single deployment prefix."""

    name_prefix: str
    storage_account: str
    ai_services: str
    search_service: str
    cosmos_account: str
    container_environment: str
    container_app: str
    graph_worker_environment: str
    graph_worker_app: str
    log_analytics_workspace: str


@dataclass(frozen=True)
class NameIssue:
    """A name collision or validation issue found during preflight."""

    resource: str
    name: str
    reason: str


def build_deployment_names(name_prefix: str) -> DeploymentNames:
    """Return the names that main.bicep derives from namePrefix."""
    return DeploymentNames(
        name_prefix=name_prefix,
        storage_account=f"{name_prefix}store",
        ai_services=f"{name_prefix}ai",
        search_service=f"{name_prefix}-search",
        cosmos_account=f"{name_prefix}cosmos",
        container_environment=f"{name_prefix}-env",
        container_app=f"{name_prefix}-lightrag",
        graph_worker_environment=f"{name_prefix}-graph-env",
        graph_worker_app=f"{name_prefix}-graphrag-d4",
        log_analytics_workspace=f"{name_prefix}-env-logs",
    )


def resolve_deployment_names(
    requested_prefix: str,
    resource_group: str,
    location: str,
    architectures: list[str],
    max_attempts: int = 8,
    blocked_prefixes: set[str] | None = None,
) -> DeploymentNames:
    """Resolve a collision-free deployment prefix for all Azure resources.

    Azure does not provide one universal name-reservation API. This function is
    the central guard for services used by Retrieve. It keeps the requested
    prefix when all globally constrained names are usable, purges matching
    soft-deleted AI Services accounts when possible, and otherwise retries with
    a short random suffix so every derived resource name moves together.
    """
    attempted: list[tuple[str, list[NameIssue]]] = []
    seen: set[str] = set()
    blocked_prefixes = blocked_prefixes or set()

    for prefix in _candidate_prefixes(requested_prefix, max_attempts):
        if prefix in seen or prefix in blocked_prefixes:
            continue
        seen.add(prefix)

        names = build_deployment_names(prefix)
        issues = _deployment_name_issues(names, resource_group, location, architectures)
        attempted.append((prefix, issues))
        if not issues:
            return names

    details = "; ".join(
        f"{prefix}: "
        + ", ".join(
            f"{issue.resource} '{issue.name}' ({issue.reason})" for issue in issues
        )
        for prefix, issues in attempted
    )
    raise RuntimeError(
        "Could not find an available Azure resource name prefix after "
        f"{len(attempted)} attempts. {details}"
    )


def is_name_collision_error(error_text: str) -> bool:
    """Return whether an ARM/Bicep failure is a global-name collision."""
    collision_markers = (
        "StorageAccountAlreadyTaken",
        "CustomDomainInUse",
        "ServiceNameUnavailable",
        "NameNotAvailable",
        "AlreadyExists",
        "Conflict",
        "InvalidResourceLocation",
        "failed provisioning state",
        "delete the previous instance",
    )
    return any(marker.lower() in error_text.lower() for marker in collision_markers)


def _failed_existing_resource_issue(resource: str, name: str, existing: Any) -> NameIssue | None:
    state = _provisioning_state(existing)
    if state == "failed":
        return NameIssue(resource, name, "existing resource is in failed provisioning state")
    if state == "deleting":
        return NameIssue(resource, name, "existing resource is still deleting")
    return None


def _provisioning_state(resource: Any) -> str:
    if not isinstance(resource, dict):
        return ""
    state = resource.get("provisioningState")
    if not state and isinstance(resource.get("properties"), dict):
        state = resource["properties"].get("provisioningState")
    return str(state or "").lower()


def _candidate_prefixes(requested_prefix: str, max_attempts: int):
    yield requested_prefix
    for _ in range(max(0, max_attempts - 1)):
        yield _prefix_with_suffix(requested_prefix, _random_suffix())


def candidate_resource_group_names(requested_name: str, max_attempts: int = 8):
    """Yield resource group names, starting with the user's requested name."""
    yield requested_name
    for _ in range(max(0, max_attempts - 1)):
        yield _resource_group_with_suffix(requested_name, _random_suffix())


def _prefix_with_suffix(requested_prefix: str, suffix: str) -> str:
    safe_base = re.sub(r"[^a-z0-9]", "", requested_prefix.lower()) or "retrieve"
    max_base_len = max(1, _MAX_PREFIX_FOR_DERIVED_NAMES - len(suffix))
    return f"{safe_base[:max_base_len]}{suffix}"


def _resource_group_with_suffix(requested_name: str, suffix: str) -> str:
    safe_base = re.sub(r"[^A-Za-z0-9_.()-]", "-", requested_name).strip(".")
    safe_base = safe_base or "rg-retrieve"
    max_base_len = max(1, _MAX_RESOURCE_GROUP_NAME_LENGTH - len(suffix) - 1)
    return f"{safe_base[:max_base_len].rstrip('.')}-{suffix}"


def _random_suffix() -> str:
    alphabet = string.ascii_lowercase + string.digits
    return "".join(random.choice(alphabet) for _ in range(_SUFFIX_LENGTH))


def _deployment_name_issues(
    names: DeploymentNames,
    resource_group: str,
    location: str,
    architectures: list[str],
) -> list[NameIssue]:
    issues: list[NameIssue] = []

    for issue in (
        _storage_name_issue(names.storage_account, resource_group),
        _ai_services_name_issue(names.ai_services, resource_group, location),
        _search_name_issue(names.search_service, resource_group),
    ):
        if issue:
            issues.append(issue)

    if "graphrag" in architectures:
        issue = _cosmos_name_issue(names.cosmos_account, resource_group)
        if issue:
            issues.append(issue)

    # Container Apps, managed environments, and Log Analytics workspaces are
    # resource-group scoped in this template. Existing same-name resources in
    # the target group are treated as idempotent redeploys, so there is no global
    # availability check to perform for LightRAG or GraphRAG worker names here.

    return issues


def _storage_name_issue(name: str, resource_group: str) -> NameIssue | None:
    existing = _az_json_or_none(
        ["storage", "account", "show", "-g", resource_group, "-n", name]
    )
    if existing:
        if issue := _failed_existing_resource_issue("storage account", name, existing):
            return issue
        return None

    result = _az_json_or_none(["storage", "account", "check-name", "--name", name])
    if _name_available(result):
        return None
    return NameIssue("storage account", name, _availability_reason(result, "name unavailable"))


def _ai_services_name_issue(name: str, resource_group: str, location: str) -> NameIssue | None:
    existing = _az_json_or_none(
        ["cognitiveservices", "account", "show", "-g", resource_group, "-n", name]
    )
    if existing:
        if issue := _failed_existing_resource_issue("AI Services account", name, existing):
            return issue
        return None

    _purge_soft_deleted_ai_services(name, resource_group, location)

    result = _check_ai_services_domain_availability(name)
    if result is None or _name_available(result):
        return None
    return NameIssue(
        "AI Services account",
        name,
        _availability_reason(result, "custom domain unavailable"),
    )


def _search_name_issue(name: str, resource_group: str) -> NameIssue | None:
    existing = _az_json_or_none(
        ["search", "service", "show", "-g", resource_group, "-n", name]
    )
    if existing:
        if issue := _failed_existing_resource_issue("search service", name, existing):
            return issue
        return None

    result = _az_json_or_none(
        [
            "search", "service", "check-name-availability",
            "--name", name,
            "--type", "searchServices",
        ]
    )
    if _name_available(result):
        return None
    return NameIssue("search service", name, _availability_reason(result, "name unavailable"))


def _cosmos_name_issue(name: str, resource_group: str) -> NameIssue | None:
    existing = _az_json_or_none(
        [
            "resource", "show",
            "-g", resource_group,
            "-n", name,
            "--resource-type", "Microsoft.DocumentDB/databaseAccounts",
        ]
    )
    if existing:
        if issue := _failed_existing_resource_issue("Cosmos DB account", name, existing):
            return issue
        return None

    exists = _az_json_or_none(["cosmosdb", "check-name-exists", "--name", name])
    if exists is False:
        return None
    if exists is True:
        return NameIssue("Cosmos DB account", name, "name already exists")
    return None


def _purge_soft_deleted_ai_services(name: str, resource_group: str, location: str) -> None:
    deleted_accounts = _az_json_or_none(["cognitiveservices", "account", "list-deleted"])
    if not isinstance(deleted_accounts, list):
        return

    for deleted in deleted_accounts:
        if str(deleted.get("name", "")).lower() != name.lower():
            continue

        deleted_rg = (
            deleted.get("resourceGroup")
            or _resource_group_from_id(deleted.get("id", ""))
            or resource_group
        )
        deleted_location = deleted.get("location") or location
        try:
            result = subprocess.run(
                [
                    AZ_COMMAND, "cognitiveservices", "account", "purge",
                    "-n", name,
                    "-g", deleted_rg,
                    "-l", deleted_location,
                    "-o", "json",
                ],
                capture_output=True,
                text=True,
                shell=False,
                timeout=_AZ_CLI_TIMEOUT_SECONDS,
            )
        except subprocess.TimeoutExpired:
            log.debug("Timed out purging soft-deleted AI Services account %s", name)
            continue
        if result.returncode != 0:
            log.debug(
                "Failed to purge soft-deleted AI Services account %s: %s",
                name,
                result.stderr,
            )


def _check_ai_services_domain_availability(name: str) -> dict[str, Any] | None:
    subscription_id = _subscription_id()
    if not subscription_id:
        return None
    url = (
        f"https://management.azure.com/subscriptions/{subscription_id}"
        "/providers/Microsoft.CognitiveServices/checkDomainAvailability"
        "?api-version=2024-10-01"
    )
    return _arm_post_json(url, {
        "type": "Microsoft.CognitiveServices/accounts",
        "subdomainName": name,
    })


def _name_available(result: Any) -> bool:
    if not isinstance(result, dict):
        return False
    for key in ("nameAvailable", "isSubdomainAvailable"):
        if key in result:
            return bool(result[key])
    return False


def _availability_reason(result: Any, fallback: str) -> str:
    if not isinstance(result, dict):
        return fallback
    reason = result.get("reason") or result.get("message")
    if isinstance(reason, str) and reason.strip():
        return reason.strip()
    return fallback


def _az_json_or_none(args: list[str]) -> Any | None:
    try:
        result = subprocess.run(
            [AZ_COMMAND] + args + ["-o", "json"],
            capture_output=True,
            text=True,
            shell=False,
            timeout=_AZ_CLI_TIMEOUT_SECONDS,
        )
    except subprocess.TimeoutExpired:
        log.debug("Timed out running az %s", " ".join(args))
        return None
    if result.returncode != 0 or not result.stdout.strip():
        return None
    try:
        return json.loads(result.stdout)
    except json.JSONDecodeError:
        return None


def _arm_post_json(url: str, body: dict[str, Any]) -> dict[str, Any] | None:
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
        log.debug("Timed out acquiring ARM token for name availability request")
        return None
    if token_result.returncode != 0 or not token_result.stdout.strip():
        return None

    response = requests.post(
        url,
        headers={"Authorization": f"Bearer {token_result.stdout.strip()}"},
        json=body,
        timeout=30,
    )
    if response.status_code >= 400:
        log.debug(
            "ARM name availability request failed: %s %s",
            response.status_code,
            response.text,
        )
        return None
    try:
        return response.json()
    except ValueError:
        return None


def _subscription_id() -> str:
    account = _az_json_or_none(["account", "show"])
    if isinstance(account, dict):
        return str(account.get("id", ""))
    return ""


def _resource_group_from_id(resource_id: str) -> str:
    parts = resource_id.split("/")
    for index, part in enumerate(parts):
        if part.lower() == "resourcegroups" and index + 1 < len(parts):
            return parts[index + 1]
    return ""
