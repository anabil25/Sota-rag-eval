from __future__ import annotations

import json
import subprocess
import time
from typing import Any
from urllib.parse import quote

import requests

from retrieve.cli_process import resolve_cli_command

_SUCCESS_STATES = {"succeeded", "success", "completed"}
_FAILURE_STATES = {
    "failed",
    "cancelled",
    "canceled",
    "stopped",
    "timedout",
    "timed_out",
}
_API_VERSION = "2025-07-01"


def _run(command: list[str]) -> subprocess.CompletedProcess[str]:
    return subprocess.run(
        resolve_cli_command(command),
        check=True,
        capture_output=True,
        text=True,
    )


def _job_url(subscription_id: str, resource_group: str, job_name: str) -> str:
    return (
        "https://management.azure.com/subscriptions/"
        f"{quote(subscription_id, safe='')}/resourceGroups/"
        f"{quote(resource_group, safe='')}/providers/Microsoft.App/jobs/"
        f"{quote(job_name, safe='')}"
    )


def _arm_headers() -> dict[str, str]:
    result = _run(
        [
            "az",
            "account",
            "get-access-token",
            "--resource",
            "https://management.azure.com/",
            "--output",
            "json",
        ]
    )
    payload = json.loads(result.stdout)
    token = str(payload.get("accessToken") or "") if isinstance(payload, dict) else ""
    if not token:
        raise RuntimeError("Azure CLI did not return an ARM access token")
    return {
        "Authorization": f"Bearer {token}",
        "Content-Type": "application/json",
    }


def _response_object(response: requests.Response, operation: str) -> dict[str, Any]:
    if response.status_code >= 400:
        details = response.text.strip()
        raise RuntimeError(
            f"{operation} failed with HTTP {response.status_code}: {details or '<empty response>'}"
        )
    payload = response.json()
    if not isinstance(payload, dict):
        raise RuntimeError(f"{operation} returned a non-object response")
    return payload


def build_execution_template(
    template: dict[str, Any],
    *,
    container_name: str,
    environment: list[str] | None,
) -> tuple[dict[str, Any], dict[str, str]]:
    rendered = {
        "containers": json.loads(json.dumps(template.get("containers"))),
    }
    if template.get("initContainers"):
        rendered["initContainers"] = json.loads(json.dumps(template["initContainers"]))
    containers = rendered.get("containers")
    if not isinstance(containers, list):
        raise ValueError("Container Apps Job template has no containers")
    matches = [container for container in containers if container.get("name") == container_name]
    if len(matches) != 1:
        raise ValueError(
            f"Container Apps Job template must contain exactly one {container_name!r} container"
        )

    overrides: dict[str, str] = {}
    for assignment in environment or []:
        name, separator, value = assignment.partition("=")
        if not separator or not name or name in overrides:
            raise ValueError(f"Invalid or duplicate job environment override: {assignment!r}")
        overrides[name] = value

    container = matches[0]
    existing = container.get("env")
    if existing is None:
        existing = []
        container["env"] = existing
    if not isinstance(existing, list):
        raise ValueError("Container Apps Job environment must be a list")
    by_name = {
        str(item.get("name")): item
        for item in existing
        if isinstance(item, dict) and item.get("name")
    }
    for name, value in overrides.items():
        item = by_name.get(name)
        if item is None:
            item = {"name": name}
            existing.append(item)
        item.pop("secretRef", None)
        item["value"] = value
    return rendered, overrides


def _execution_environment(execution: dict[str, Any], container_name: str) -> dict[str, str]:
    template = (execution.get("properties") or {}).get("template") or {}
    containers = template.get("containers") or []
    matches = [container for container in containers if container.get("name") == container_name]
    if len(matches) != 1:
        return {}
    return {
        str(item.get("name")): str(item.get("value") or "")
        for item in matches[0].get("env") or []
        if isinstance(item, dict) and item.get("name")
    }


def start_container_job(
    *,
    job_name: str,
    resource_group: str,
    subscription_id: str = "",
    environment: list[str] | None = None,
) -> str:
    if not subscription_id:
        raise ValueError("Container Apps Job start requires a subscription ID")
    url = _job_url(subscription_id, resource_group, job_name)
    headers = _arm_headers()
    job = _response_object(
        requests.get(
            url,
            params={"api-version": _API_VERSION},
            headers=headers,
            timeout=(10, 60),
        ),
        "Container Apps Job lookup",
    )
    template, overrides = build_execution_template(
        (job.get("properties") or {}).get("template") or {},
        container_name="graphrag",
        environment=environment,
    )
    execution = _response_object(
        requests.post(
            f"{url}/start",
            params={"api-version": _API_VERSION},
            headers=headers,
            json=template,
            timeout=(10, 120),
        ),
        "Container Apps Job start",
    )
    execution_name = str(execution.get("name") or "").strip()
    if not execution_name:
        raise RuntimeError("Container Apps Job did not return an execution name")
    actual_environment = _execution_environment(execution, "graphrag")
    if any(actual_environment.get(name) != value for name, value in overrides.items()):
        execution = get_container_job_execution(
            job_name=job_name,
            execution_name=execution_name,
            resource_group=resource_group,
            subscription_id=subscription_id,
        )
        actual_environment = _execution_environment(execution, "graphrag")
    if any(actual_environment.get(name) != value for name, value in overrides.items()):
        stop_container_job(
            job_name=job_name,
            execution_name=execution_name,
            resource_group=resource_group,
            subscription_id=subscription_id,
        )
        raise RuntimeError("Container Apps Job execution did not preserve environment overrides")
    return execution_name


def stop_container_job(
    *,
    job_name: str,
    execution_name: str,
    resource_group: str,
    subscription_id: str,
) -> None:
    _run(
        [
            "az",
            "containerapp",
            "job",
            "stop",
            "--resource-group",
            resource_group,
            "--name",
            job_name,
            "--job-execution-name",
            execution_name,
            "--subscription",
            subscription_id,
            "--output",
            "none",
        ]
    )


def get_container_job_execution(
    *,
    job_name: str,
    execution_name: str,
    resource_group: str,
    subscription_id: str = "",
) -> dict[str, Any]:
    if not subscription_id:
        raise ValueError("Container Apps Job lookup requires a subscription ID")
    url = (
        f"{_job_url(subscription_id, resource_group, job_name)}/executions/"
        f"{quote(execution_name, safe='')}"
    )
    return _response_object(
        requests.get(
            url,
            params={"api-version": _API_VERSION},
            headers=_arm_headers(),
            timeout=(10, 60),
        ),
        "Container Apps Job execution lookup",
    )


def container_job_state(execution: dict[str, Any]) -> str:
    return str(
        (execution.get("properties") or {}).get("status") or execution.get("status") or ""
    ).strip().lower()


def wait_for_container_job(
    *,
    job_name: str,
    execution_name: str,
    resource_group: str,
    subscription_id: str = "",
    delays: tuple[int, ...] = tuple(5 for _ in range(120)),
) -> dict[str, Any]:
    for attempt in range(len(delays) + 1):
        execution = get_container_job_execution(
            job_name=job_name,
            execution_name=execution_name,
            resource_group=resource_group,
            subscription_id=subscription_id,
        )
        state = container_job_state(execution)
        if state in _SUCCESS_STATES:
            return execution
        if state in _FAILURE_STATES:
            details = str((execution.get("properties") or {}).get("statusDetails") or "")
            raise RuntimeError(
                f"Container Apps Job execution ended as {state}: {details}".strip()
            )
        if attempt < len(delays):
            time.sleep(delays[attempt])
    raise RuntimeError("Container Apps Job execution did not complete before timeout")


def get_container_job_logs(
    *,
    job_name: str,
    execution_name: str,
    resource_group: str,
    subscription_id: str = "",
    tail: int = 100,
    require_result: bool = False,
    retained_delays: tuple[int, ...] = (5, 10, 20, 30, 60, 60, 120, 120, 120),
) -> str:
    command = [
        "az",
        "containerapp",
        "job",
        "logs",
        "show",
        "--name",
        job_name,
        "--resource-group",
        resource_group,
        "--execution",
        execution_name,
        "--container",
        "graphrag",
        "--tail",
        str(tail),
    ]
    if subscription_id:
        command.extend(["--subscription", subscription_id])
    for attempt in range(len(retained_delays) + 1):
        try:
            result = _run(command)
            logs = "\n".join(
                part.strip() for part in (result.stdout, result.stderr) if part.strip()
            )
        except subprocess.CalledProcessError as exc:
            details = "\n".join(
                part.strip()
                for part in (exc.stdout, exc.stderr)
                if isinstance(part, str) and part.strip()
            )
            if "No replicas found" not in details:
                raise
            logs = _get_retained_container_job_logs(
                execution_name=execution_name,
                resource_group=resource_group,
                subscription_id=subscription_id,
            )
        if not require_result or "RETRIEVE_JOB_RESULT=" in logs:
            return logs
        if attempt < len(retained_delays):
            time.sleep(retained_delays[attempt])
    raise RuntimeError(
        "Completed Container Apps Job logs contain no retained Retrieve result"
    )


def _get_retained_container_job_logs(
    *,
    execution_name: str,
    resource_group: str,
    subscription_id: str,
) -> str:
    workspace_command = [
        "az",
        "monitor",
        "log-analytics",
        "workspace",
        "list",
        "--resource-group",
        resource_group,
        "--output",
        "json",
        "--only-show-errors",
    ]
    if subscription_id:
        workspace_command.extend(["--subscription", subscription_id])
    workspace_result = _run(workspace_command)
    workspaces = json.loads(workspace_result.stdout)
    if not isinstance(workspaces, list) or len(workspaces) != 1:
        raise RuntimeError(
            "Completed Container Apps Job logs require exactly one Log Analytics "
            "workspace in the resource group"
        )
    workspace_id = str(workspaces[0].get("customerId") or "").strip()
    if not workspace_id:
        raise RuntimeError("Log Analytics workspace has no customer ID")

    escaped_execution = execution_name.replace("'", "''")
    kusto = (
        "ContainerAppConsoleLogs_CL "
        f"| where ContainerGroupName_s startswith '{escaped_execution}' "
        "| project TimeGenerated, Log_s | order by TimeGenerated asc"
    )
    query_command = [
        "az",
        "monitor",
        "log-analytics",
        "query",
        "--workspace",
        workspace_id,
        "--analytics-query",
        kusto,
        "--output",
        "json",
        "--only-show-errors",
    ]
    if subscription_id:
        query_command.extend(["--subscription", subscription_id])
    query_result = _run(query_command)
    rows = json.loads(query_result.stdout)
    if not isinstance(rows, list):
        raise RuntimeError("Log Analytics returned invalid Container Apps Job logs")
    logs = [str(row.get("Log_s") or "") for row in rows if isinstance(row, dict)]
    retained = "\n".join(line for line in logs if line)
    return retained
