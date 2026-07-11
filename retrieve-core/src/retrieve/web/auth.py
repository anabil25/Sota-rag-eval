"""Authentication and authorization for Retrieve mutation APIs."""

from __future__ import annotations

import base64
import json
import os
from dataclasses import dataclass
from typing import Any

from fastapi import HTTPException, Request

_ROLE_CLAIM_TYPES = {
    "roles",
    "role",
    "http://schemas.microsoft.com/ws/2008/06/identity/claims/role",
}
_ID_CLAIM_TYPES = {
    "http://schemas.microsoft.com/identity/claims/objectidentifier",
    "oid",
    "sub",
}
_NAME_CLAIM_TYPES = {
    "name",
    "preferred_username",
    "http://schemas.xmlsoap.org/ws/2005/05/identity/claims/name",
}
_LOOPBACK_HOSTS = {"127.0.0.1", "::1", "localhost", "testclient"}


@dataclass(frozen=True)
class AuthenticatedPrincipal:
    """Minimal identity information retained for authorization/audit."""

    principal_id: str
    name: str
    roles: tuple[str, ...]
    provider: str


def _auth_mode() -> str:
    configured = os.environ.get("RETRIEVE_AUTH_MODE", "").strip().lower()
    if configured:
        return configured
    if os.environ.get("CONTAINER_APP_NAME") or os.environ.get("WEBSITE_SITE_NAME"):
        return "easy_auth"
    return "local"


def _decode_easy_auth_principal(encoded: str) -> dict[str, Any]:
    try:
        padding = "=" * (-len(encoded) % 4)
        payload = base64.b64decode(encoded + padding, validate=True)
        principal = json.loads(payload.decode("utf-8"))
    except (ValueError, UnicodeDecodeError, json.JSONDecodeError) as exc:
        raise HTTPException(status_code=401, detail="Invalid authenticated principal") from exc
    if not isinstance(principal, dict):
        raise HTTPException(status_code=401, detail="Invalid authenticated principal")
    return principal


def _claim_values(principal: dict[str, Any], claim_types: set[str]) -> list[str]:
    values: list[str] = []
    claims = principal.get("claims")
    if not isinstance(claims, list):
        return values
    for claim in claims:
        if not isinstance(claim, dict):
            continue
        claim_type = str(claim.get("typ") or claim.get("type") or "").lower()
        if claim_type not in claim_types:
            continue
        value = claim.get("val", claim.get("value"))
        if isinstance(value, list):
            values.extend(str(item) for item in value if str(item))
        elif value is not None and str(value):
            values.append(str(value))
    return values


def authorize_mutation(request: Request) -> AuthenticatedPrincipal:
    """Authorize one mutation request using local or Azure Easy Auth identity."""
    mode = _auth_mode()
    if mode == "local":
        environment = os.environ.get("RETRIEVE_ENVIRONMENT", "development").lower()
        if environment in {"prod", "production"} and os.environ.get(
            "RETRIEVE_ALLOW_INSECURE_LOCAL", ""
        ).lower() not in {"1", "true", "yes"}:
            raise HTTPException(
                status_code=503,
                detail="Local authentication mode is forbidden in production",
            )
        host = request.client.host if request.client else ""
        if host not in _LOOPBACK_HOSTS:
            raise HTTPException(
                status_code=403,
                detail="Local mutation APIs are restricted to loopback clients",
            )
        return AuthenticatedPrincipal(
            principal_id="local-development",
            name="Local development",
            roles=("Retrieve.Operator",),
            provider="local",
        )

    if mode != "easy_auth":
        raise HTTPException(status_code=503, detail="Unsupported Retrieve authentication mode")

    encoded = request.headers.get("x-ms-client-principal", "").strip()
    if not encoded:
        raise HTTPException(status_code=401, detail="Authentication required")
    principal = _decode_easy_auth_principal(encoded)
    roles = tuple(dict.fromkeys(_claim_values(principal, _ROLE_CLAIM_TYPES)))
    required_role = os.environ.get("RETRIEVE_MUTATION_ROLE", "Retrieve.Operator").strip()
    if required_role and required_role not in roles:
        raise HTTPException(status_code=403, detail="Retrieve mutation role required")

    principal_ids = _claim_values(principal, _ID_CLAIM_TYPES)
    names = _claim_values(principal, _NAME_CLAIM_TYPES)
    principal_id = str(principal.get("user_id") or (principal_ids[0] if principal_ids else ""))
    if not principal_id:
        raise HTTPException(status_code=401, detail="Authenticated principal has no identity")
    return AuthenticatedPrincipal(
        principal_id=principal_id,
        name=names[0] if names else principal_id,
        roles=roles,
        provider=str(principal.get("auth_typ") or "easy_auth"),
    )
