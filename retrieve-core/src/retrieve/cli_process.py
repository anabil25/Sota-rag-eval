"""Cross-platform executable resolution for Azure command-line tools."""

from __future__ import annotations

import shutil
from collections.abc import Sequence


def resolve_cli_command(command: Sequence[str]) -> list[str]:
    """Resolve a CLI shim to its executable path without invoking a shell."""
    if not command:
        raise ValueError("CLI command cannot be empty")
    executable = shutil.which(command[0])
    if executable is None:
        raise FileNotFoundError(f"Required CLI is not installed: {command[0]}")
    return [executable, *command[1:]]
