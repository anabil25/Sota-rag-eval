"""Remove cross-resource dependencies before azd deletes the isolated environment."""

from __future__ import annotations

import json
import os
import subprocess
import sys
from pathlib import Path

CORE_SRC = Path(__file__).resolve().parents[1] / "retrieve-core" / "src"
if str(CORE_SRC) not in sys.path:
    sys.path.insert(0, str(CORE_SRC))

from retrieve.cli_process import resolve_cli_command  # noqa: E402

PROTECTED_RESOURCE_GROUPS = {
    "rg-ret-test2",
    *{
        name.strip().lower()
        for name in os.environ.get("RETRIEVE_PROTECTED_RESOURCE_GROUPS", "").split(",")
        if name.strip()
    },
}


def _run(command: list[str], *, check: bool = True) -> subprocess.CompletedProcess[str]:
    return subprocess.run(
        resolve_cli_command(command),
        check=check,
        capture_output=True,
        text=True,
    )


def _azd_value(name: str) -> str:
    result = _run(["azd", "env", "get-value", name], check=False)
    return result.stdout.strip() if result.returncode == 0 else ""


def main() -> None:
    environment_name = _azd_value("AZURE_ENV_NAME")
    subscription_id = _azd_value("AZURE_SUBSCRIPTION_ID")
    resource_group = _azd_value("AZURE_RESOURCE_GROUP") or f"rg-{environment_name}"
    resource_token = _azd_value("AZURE_RESOURCE_TOKEN")
    expected_group = f"rg-{environment_name}"
    expected_search = f"azsr{resource_token}"
    search_service = _azd_value("AZURE_SEARCH_SERVICE_NAME") or expected_search

    if not environment_name or not subscription_id or not resource_token:
        raise RuntimeError("Incomplete azd environment contract for pre-down cleanup")
    if resource_group.lower() in PROTECTED_RESOURCE_GROUPS:
        raise RuntimeError(f"Refusing pre-down cleanup for protected group {resource_group}")
    if resource_group != expected_group or search_service != expected_search:
        raise RuntimeError("Pre-down Search target does not match the azd environment contract")

    show = _run(
        [
            "az",
            "search",
            "shared-private-link-resource",
            "show",
            "--subscription",
            subscription_id,
            "--resource-group",
            resource_group,
            "--service-name",
            search_service,
            "--name",
            "storage-blob",
            "--output",
            "json",
        ],
        check=False,
    )
    if show.returncode != 0:
        details = (show.stderr or show.stdout).lower()
        if any(
            marker in details
            for marker in (
                "not found",
                "could not be found",
                "resourcenotfound",
                "resourcegroupnotfound",
            )
        ):
            print("[predown] Search shared private link already absent")
            return
        raise RuntimeError((show.stderr or show.stdout).strip())

    payload = json.loads(show.stdout)
    expected_id = (
        f"/subscriptions/{subscription_id}/resourceGroups/{resource_group}/providers/"
        f"Microsoft.Search/searchServices/{search_service}/sharedPrivateLinkResources/"
        "storage-blob"
    )
    if str(payload.get("id") or "").lower() != expected_id.lower():
        raise RuntimeError("Pre-down shared private link ID does not match the expected target")

    _run(
        [
            "az",
            "search",
            "shared-private-link-resource",
            "delete",
            "--subscription",
            subscription_id,
            "--resource-group",
            resource_group,
            "--service-name",
            search_service,
            "--name",
            "storage-blob",
            "--yes",
        ]
    )
    print("[predown] removed Search shared private link storage-blob")


if __name__ == "__main__":
    try:
        main()
    except (RuntimeError, ValueError, json.JSONDecodeError, subprocess.CalledProcessError) as exc:
        print(f"[predown] {exc}", file=sys.stderr)
        raise SystemExit(1) from exc
