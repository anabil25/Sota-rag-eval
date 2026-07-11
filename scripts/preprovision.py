"""Interactive, idempotent azd preprovision configuration."""

from __future__ import annotations

import os
import subprocess
import sys
from pathlib import Path

CORE_SRC = Path(__file__).resolve().parents[1] / "retrieve-core" / "src"
if str(CORE_SRC) not in sys.path:
    sys.path.insert(0, str(CORE_SRC))

from retrieve.cli_process import resolve_cli_command  # noqa: E402

REGIONS = (
    "northcentralus",
    "westus3",
    "centralus",
    "southcentralus",
    "eastus2",
)
PROTECTED_RESOURCE_GROUPS = {
    resource_group.strip()
    for resource_group in os.environ.get(
        "RETRIEVE_PROTECTED_RESOURCE_GROUPS", ""
    ).split(",")
    if resource_group.strip()
}


def _azd(*args: str, check: bool = True) -> subprocess.CompletedProcess[str]:
    return subprocess.run(
        resolve_cli_command(["azd", *args]),
        check=check,
        capture_output=True,
        text=True,
    )


def get_value(name: str) -> str:
    result = _azd("env", "get-value", name, check=False)
    return result.stdout.strip() if result.returncode == 0 else ""


def set_value(name: str, value: str) -> None:
    _azd("env", "set", name, value)


def _select_region(current: str) -> str:
    non_interactive = os.environ.get("CI", "").lower() == "true" or os.environ.get(
        "RETRIEVE_NON_INTERACTIVE", ""
    ).lower() in {"1", "true", "yes"}
    if non_interactive:
        if current not in REGIONS:
            raise RuntimeError(
                "Non-interactive deployment requires AZURE_LOCATION to be one of: "
                + ", ".join(REGIONS)
            )
        return current

    print("Select one region for the entire Retrieve stack:")
    for index, region in enumerate(REGIONS, start=1):
        marker = " (current)" if region == current else ""
        print(f"  {index}) {region}{marker}")
    default = REGIONS.index(current) + 1 if current in REGIONS else 1
    choice = input(f"Region [default {default}]: ").strip()
    if not choice:
        return REGIONS[default - 1]
    if not choice.isdigit() or not 1 <= int(choice) <= len(REGIONS):
        raise ValueError(f"Invalid region selection: {choice}")
    return REGIONS[int(choice) - 1]


def main() -> None:
    environment_name = get_value("AZURE_ENV_NAME") or os.environ.get(
        "AZURE_ENV_NAME", ""
    )
    resource_group = f"rg-{environment_name}" if environment_name else ""
    allow_protected = os.environ.get("RETRIEVE_ALLOW_PROTECTED_ENV", "").lower() in {
        "1",
        "true",
        "yes",
    }
    if resource_group in PROTECTED_RESOURCE_GROUPS and not allow_protected:
        raise RuntimeError(
            f"Refusing to provision protected live resource group {resource_group}. "
            "Select a new azd environment name."
        )

    selected = get_value("RETRIEVE_DEPLOYMENT_REGION")
    if selected:
        if selected not in REGIONS:
            raise RuntimeError(f"Unsupported persisted deployment region: {selected}")
        set_value("AZURE_LOCATION", selected)
        print(f"Using persisted whole-stack region: {selected}")
        return

    current = get_value("AZURE_LOCATION") or os.environ.get("AZURE_LOCATION", "")
    selected = _select_region(current)
    set_value("RETRIEVE_DEPLOYMENT_REGION", selected)
    set_value("AZURE_LOCATION", selected)
    set_value("RETRIEVE_REGION_CANDIDATES", ",".join(REGIONS))
    print(f"Whole-stack deployment region set to {selected}.")
    print(
        "If Azure reports regional capacity exhaustion, choose the next region and "
        "rerun azd up; Bicep itself cannot catch a failed deployment."
    )


if __name__ == "__main__":
    try:
        main()
    except (RuntimeError, ValueError, subprocess.CalledProcessError) as exc:
        print(f"[preprovision] {exc}", file=sys.stderr)
        raise SystemExit(1) from exc
