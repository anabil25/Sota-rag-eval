from __future__ import annotations

import base64
import json
import re
from typing import Any

RESULT_PREFIX = "RETRIEVE_JOB_RESULT="
_RESULT_PATTERN = re.compile(rf"{RESULT_PREFIX}([A-Za-z0-9_=-]+)")


def encode_payload(payload: dict[str, Any]) -> str:
    serialized = json.dumps(
        payload,
        ensure_ascii=False,
        separators=(",", ":"),
        sort_keys=True,
    ).encode("utf-8")
    return base64.urlsafe_b64encode(serialized).decode("ascii")


def decode_payload(encoded: str) -> dict[str, Any]:
    try:
        payload = json.loads(base64.urlsafe_b64decode(encoded).decode("utf-8"))
    except (ValueError, UnicodeDecodeError, json.JSONDecodeError) as exc:
        raise ValueError("Container Apps Job payload is invalid") from exc
    if not isinstance(payload, dict):
        raise ValueError("Container Apps Job payload must be a JSON object")
    return payload


def format_job_result(payload: dict[str, Any]) -> str:
    return f"{RESULT_PREFIX}{encode_payload(payload)}"


def parse_job_result(log_output: str) -> dict[str, Any]:
    matches = _RESULT_PATTERN.findall(log_output)
    if not matches:
        raise ValueError("Container Apps Job logs contain no Retrieve result")
    return decode_payload(matches[-1])
