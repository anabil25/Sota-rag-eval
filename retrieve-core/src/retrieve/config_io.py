"""Locked, validated, atomic YAML configuration updates."""

from __future__ import annotations

import os
import stat
import tempfile
from collections.abc import Callable
from pathlib import Path
from typing import Any

import yaml
from filelock import FileLock

YamlMapping = dict[str, Any]


def atomic_update_yaml(
    path: str | Path,
    update: Callable[[YamlMapping], YamlMapping | None],
    *,
    lock_timeout: float = 10.0,
) -> YamlMapping:
    """Update a YAML mapping under a cross-process lock and atomic replace."""
    target = Path(path).resolve()
    target.parent.mkdir(parents=True, exist_ok=True)
    lock = FileLock(f"{target}.lock", timeout=lock_timeout)

    with lock:
        existing_mode: int | None = None
        if target.exists():
            existing_mode = stat.S_IMODE(target.stat().st_mode)
            parsed = yaml.safe_load(target.read_text(encoding="utf-8"))
            if parsed is None:
                raw: YamlMapping = {}
            elif isinstance(parsed, dict):
                raw = parsed
            else:
                raise ValueError(f"YAML configuration root must be a mapping: {target}")
        else:
            raw = {}

        result = update(dict(raw))
        updated = raw if result is None else result
        if not isinstance(updated, dict):
            raise ValueError("YAML update must return a mapping or None")

        serialized = yaml.safe_dump(
            updated,
            allow_unicode=True,
            default_flow_style=False,
            sort_keys=False,
        )
        round_trip = yaml.safe_load(serialized)
        if round_trip != updated:
            raise ValueError("YAML configuration failed round-trip validation")

        temporary_path: Path | None = None
        try:
            with tempfile.NamedTemporaryFile(
                mode="w",
                encoding="utf-8",
                newline="\n",
                dir=target.parent,
                prefix=f".{target.name}.",
                suffix=".tmp",
                delete=False,
            ) as temporary:
                temporary.write(serialized)
                temporary.flush()
                os.fsync(temporary.fileno())
                temporary_path = Path(temporary.name)
            if existing_mode is not None:
                os.chmod(temporary_path, existing_mode)
            os.replace(temporary_path, target)
            temporary_path = None
        finally:
            if temporary_path is not None:
                temporary_path.unlink(missing_ok=True)

        return updated
