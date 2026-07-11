"""Foundry embedding discovery helpers for the Retrieve UI."""

from __future__ import annotations

import json
import subprocess
import sys
from typing import Any

IS_WINDOWS = sys.platform == "win32"

EMBEDDING_KEYWORDS = (
    "embed",
    "embedding",
    "bge",
    "e5",
    "gte",
    "jina",
    "instructor",
)

KNOWN_EMBEDDING_CATALOG: list[dict[str, Any]] = [
    {
        "name": "text-embedding-3-large",
        "label": "Azure OpenAI text-embedding-3-large",
        "provider": "azure_openai",
        "dimensions": 3072,
        "vectorizer_source": "azure_openai",
        "model_id": "text-embedding-3-large",
        "deployable": False,
    },
    {
        "name": "text-embedding-3-small",
        "label": "Azure OpenAI text-embedding-3-small",
        "provider": "azure_openai",
        "dimensions": 1536,
        "vectorizer_source": "azure_openai",
        "model_id": "text-embedding-3-small",
        "deployable": False,
    },
    {
        "name": "Cohere-embed-v3-english",
        "label": "Cohere Embed v3 English",
        "provider": "cohere",
        "dimensions": 1024,
        "vectorizer_source": "foundry_cohere",
        "model_id": "azureml://registries/azureml-cohere/models/Cohere-embed-v3-english",
        "deployable": True,
    },
    {
        "name": "Cohere-embed-v3-multilingual",
        "label": "Cohere Embed v3 Multilingual",
        "provider": "cohere",
        "dimensions": 1024,
        "vectorizer_source": "foundry_cohere",
        "model_id": "azureml://registries/azureml-cohere/models/Cohere-embed-v3-multilingual",
        "deployable": True,
    },
    {
        "name": "Cohere-embed-v4",
        "label": "Cohere Embed v4",
        "provider": "cohere",
        "dimensions": 1536,
        "vectorizer_source": "foundry_cohere",
        "model_id": "azureml://registries/azureml-cohere/models/Cohere-embed-v4",
        "deployable": True,
    },
    {
        "name": "bge-m3",
        "label": "BGE-M3",
        "provider": "huggingface",
        "dimensions": 1024,
        "vectorizer_source": "custom_web_api",
        "model_id": "",
        "deployable": False,
    },
]


def _run_az(args: list[str]) -> tuple[int, str, str]:
    result = subprocess.run(
        ["az", *args],
        capture_output=True,
        text=True,
        shell=IS_WINDOWS,
    )
    return result.returncode, result.stdout, result.stderr


def _az_json(args: list[str]) -> list[dict[str, Any]]:
    code, stdout, stderr = _run_az([*args, "-o", "json"])
    if code != 0:
        raise RuntimeError(stderr.strip() or stdout.strip() or "az command failed")
    parsed = json.loads(stdout or "[]")
    if isinstance(parsed, list):
        return [item for item in parsed if isinstance(item, dict)]
    return [parsed] if isinstance(parsed, dict) else []


def _looks_like_embedding(value: str) -> bool:
    normalized = value.lower()
    return any(keyword in normalized for keyword in EMBEDDING_KEYWORDS)


def catalog_embedding_presets(query: str = "") -> list[dict[str, Any]]:
    normalized = query.lower().strip()
    if not normalized:
        return KNOWN_EMBEDDING_CATALOG
    return [
        model
        for model in KNOWN_EMBEDDING_CATALOG
        if normalized in model["name"].lower()
        or normalized in model["label"].lower()
        or normalized in model["provider"].lower()
    ]


def search_foundry_embedding_catalog(query: str = "") -> dict[str, Any]:
    """Return curated presets plus best-effort Azure ML registry matches."""
    results = [dict(item, source="preset") for item in catalog_embedding_presets(query)]
    seen = {item.get("model_id") or item.get("name") for item in results}
    registry_errors: list[str] = []

    for registry in ("azureml-cohere", "azureml"):
        try:
            models = _az_json(
                [
                    "ml",
                    "model",
                    "list",
                    "--registry-name",
                    registry,
                    "--max-results",
                    "100",
                ]
            )
        except Exception as exc:
            registry_errors.append(f"{registry}: {exc}")
            continue

        for model in models:
            name = str(model.get("name") or "")
            model_id = str(model.get("id") or model.get("assetId") or "")
            haystack = " ".join([name, model_id])
            if query and query.lower() not in haystack.lower():
                continue
            if not _looks_like_embedding(haystack):
                continue
            identity = model_id or f"{registry}:{name}"
            if identity in seen:
                continue
            seen.add(identity)
            results.append(
                {
                    "name": name,
                    "label": name,
                    "provider": registry,
                    "dimensions": 0,
                    "vectorizer_source": "custom_web_api",
                    "model_id": model_id,
                    "deployable": bool(model_id),
                    "source": "registry",
                }
            )

    return {"items": results, "errors": registry_errors}


def list_deployed_foundry_embeddings(resource_group: str, workspace_name: str) -> dict[str, Any]:
    if not resource_group or not workspace_name:
        return {"items": [], "errors": ["resource_group and workspace_name are required"]}

    errors: list[str] = []
    items: list[dict[str, Any]] = []
    try:
        endpoints = _az_json(
            [
                "ml",
                "serverless-endpoint",
                "list",
                "--resource-group",
                resource_group,
                "--workspace-name",
                workspace_name,
            ]
        )
    except Exception as exc:
        return {"items": [], "errors": [str(exc)]}

    for endpoint in endpoints:
        name = str(endpoint.get("name") or "")
        model_id = str(endpoint.get("model_id") or endpoint.get("modelId") or "")
        scoring_uri = str(endpoint.get("scoring_uri") or endpoint.get("scoringUri") or "")
        if not _looks_like_embedding(" ".join([name, model_id])):
            continue
        if not scoring_uri and name:
            code, stdout, stderr = _run_az(
                [
                    "ml",
                    "serverless-endpoint",
                    "show",
                    "--name",
                    name,
                    "--resource-group",
                    resource_group,
                    "--workspace-name",
                    workspace_name,
                    "--query",
                    "scoring_uri",
                    "-o",
                    "tsv",
                ]
            )
            if code == 0:
                scoring_uri = stdout.strip()
            else:
                errors.append(stderr.strip() or f"Could not read scoring URI for {name}")
        vectorizer_source = "foundry_cohere" if "cohere" in name.lower() else "custom_web_api"
        items.append(
            {
                "name": name,
                "model_id": model_id,
                "uri": scoring_uri,
                "vectorizer_source": vectorizer_source,
                "dimensions": 1024 if "cohere-embed-v3" in name.lower() else 0,
            }
        )
    return {"items": items, "errors": errors}
