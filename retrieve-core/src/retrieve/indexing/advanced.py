"""Advanced search index builders — multi-vector, agentic-KB, GraphRAG, LightRAG.

Extends search_index.py with builders for the §15 advanced architectures.

Per docs:
- Multi-vector: AML skill + AML vectorizer for Foundry model catalog models
- Agentic KB: Knowledge Source + Knowledge Base on top of existing hybrid index
- GraphRAG: graphrag package handles indexing; we build a lightweight search index for entities
- LightRAG: lightrag-hku package; we configure the backend to use Azure OpenAI
"""

from __future__ import annotations

import asyncio
import hashlib
import importlib.util
import json
import logging
import os
import subprocess
import sys
import uuid
from collections.abc import Sequence
from typing import Any
from urllib.parse import quote

import requests
from azure.identity import DefaultAzureCredential
from azure.search.documents.indexes import SearchIndexClient, SearchIndexerClient
from azure.search.documents.indexes.models import (
    HnswAlgorithmConfiguration,
    HnswParameters,
    InputFieldMappingEntry,
    OutputFieldMappingEntry,
    SearchField,
    SearchFieldDataType,
    SearchIndex,
    SearchIndexer,
    SearchIndexerDataContainer,
    SearchIndexerDataSourceConnection,
    SearchIndexerIndexProjection,
    SearchIndexerIndexProjectionSelector,
    SearchIndexerIndexProjectionsParameters,
    SearchIndexerSkillset,
    SemanticConfiguration,
    SemanticField,
    SemanticPrioritizedFields,
    SemanticSearch,
    SplitSkill,
    VectorSearch,
    VectorSearchProfile,
)
from rich.console import Console

from retrieve.backoff import BackoffPolicy, call_with_backoff, is_retryable_http_response
from retrieve.graphrag.safety import GraphRagRunScope, validate_graphrag_run_scope
from retrieve.graphrag.settings import build_graphrag_settings, validate_graphrag_settings
from retrieve.ingest.manifest import load_corpus_manifest
from retrieve.observability import emit_progress
from retrieve.registry.models import EMBEDDING_MODELS

log = logging.getLogger(__name__)
console = Console()

IS_WINDOWS = sys.platform == "win32"
SEARCH_AGENTIC_API_VERSION = "2025-11-01-preview"


def _embedding_dimensions(embedding_model: str, foundry_model_name: str = "") -> int:
    """Return vector dimensions for Azure OpenAI and Foundry catalog embeddings."""
    normalized = (foundry_model_name or embedding_model).lower()
    if "cohere-embed-v3" in normalized:
        return 1024
    if "cohere-embed-v4" in normalized:
        return 1536
    if "bge-m3" in normalized:
        return 1024
    model = EMBEDDING_MODELS.get(embedding_model)
    if model:
        return model.dimensions
    return 3072 if "large" in embedding_model else 1536


def _custom_embedding_dimensions(embedding_model: str, dimensions: int) -> int:
    if dimensions > 0:
        return dimensions
    model = EMBEDDING_MODELS.get(embedding_model)
    if model:
        return model.dimensions
    raise ValueError(
        "custom_embedding_dimensions is required for custom embedding endpoints "
        "unless embedding_model is registered with known dimensions"
    )


def _search_admin_headers(credential: DefaultAzureCredential) -> dict[str, str]:
    token = credential.get_token("https://search.azure.com/.default").token
    return {
        "authorization": f"Bearer {token}",
        "content-type": "application/json",
    }


def _put_search_resource(
    endpoint: str,
    path: str,
    payload: dict[str, Any],
    credential: DefaultAzureCredential,
    api_version: str = "2024-11-01-preview",
) -> None:
    separator = "&" if "?" in path else "?"
    url = f"{endpoint.rstrip('/')}/{path.lstrip('/')}{separator}api-version={api_version}"
    response = requests.put(
        url,
        headers=_search_admin_headers(credential),
        json=payload,
        timeout=60,
    )
    if response.status_code >= 400:
        raise RuntimeError(
            f"Search REST PUT failed for {path}: {response.status_code} {response.text}"
        )


def _serialized_fields(fields: Sequence[Any]) -> list[dict[str, Any]]:
    return [field.serialize() if hasattr(field, "serialize") else dict(field) for field in fields]


# ── Foundry model catalog helpers ─────────────────────────────────────
# Priority item: programmatic deployment of Foundry catalog embedding models
# for AI Search integrated vectorization via CLI.


def deploy_foundry_catalog_model(
    model_id: str,
    endpoint_name: str,
    project_name: str,
    resource_group: str,
) -> dict[str, str]:
    """Deploy a serverless embedding model from the Foundry model catalog via az ml CLI.

    Per https://learn.microsoft.com/azure/search/vector-search-integrated-vectorization-ai-studio:
    - Requires `az extension add -n ml`
    - Creates marketplace subscription + serverless endpoint
    - Returns dict with 'uri', 'key', 'model_name'

    Args:
        model_id: Full model ID (e.g., 'azureml://registries/azureml-cohere/models/Cohere-embed-v3-english')
        endpoint_name: Name for the serverless endpoint
        project_name: Foundry project (workspace) name
        resource_group: Azure resource group

    Returns:
        Dict with 'uri', 'key', and 'model_name' keys.
    """
    import tempfile
    from pathlib import Path

    # Ensure ml extension is installed
    subprocess.run(
        ["az", "extension", "add", "-n", "ml", "--yes"],
        capture_output=True, text=True, shell=IS_WINDOWS,
    )

    # Set defaults
    subprocess.run(
        ["az", "configure", "--defaults",
         f"workspace={project_name}", f"group={resource_group}"],
        capture_output=True, text=True, shell=IS_WINDOWS,
    )

    # 1. Create marketplace subscription
    sub_yaml = Path(tempfile.gettempdir()) / "retrieve-model-subscribe.yaml"
    sub_yaml.write_text(
        f"name: {endpoint_name}-subscription\n"
        f"model_id: {model_id}\n",
        encoding="utf-8",
    )

    console.print(f"  Creating marketplace subscription for {model_id}...")
    result = subprocess.run(
        ["az", "ml", "marketplace-subscription", "create", "--file", str(sub_yaml)],
        capture_output=True, text=True, shell=IS_WINDOWS,
    )
    if result.returncode != 0 and "already exists" not in result.stderr.lower():
        log.warning("Marketplace subscription creation warning: %s", result.stderr.strip())

    # 2. Create serverless endpoint
    ep_yaml = Path(tempfile.gettempdir()) / "retrieve-model-endpoint.yaml"
    ep_yaml.write_text(
        f"name: {endpoint_name}\n"
        f"model_id: {model_id}\n",
        encoding="utf-8",
    )

    console.print(f"  Creating serverless endpoint '{endpoint_name}'...")
    result = subprocess.run(
        ["az", "ml", "serverless-endpoint", "create", "--file", str(ep_yaml)],
        capture_output=True, text=True, shell=IS_WINDOWS,
    )
    if result.returncode != 0 and "already exists" not in result.stderr.lower():
        raise RuntimeError(f"Failed to create serverless endpoint: {result.stderr.strip()}")

    # 3. Get endpoint URI
    uri_result = subprocess.run(
        ["az", "ml", "serverless-endpoint", "show",
         "--name", endpoint_name, "--query", "scoring_uri", "-o", "tsv"],
        capture_output=True, text=True, shell=IS_WINDOWS,
    )
    uri = uri_result.stdout.strip() if uri_result.returncode == 0 else ""

    # 4. Get endpoint key. Cohere model catalog integration doesn't support
    # token authentication in Azure AI Search, so the skill/vectorizer need a key.
    key_result = subprocess.run(
        ["az", "ml", "serverless-endpoint", "get-credentials",
         "--name", endpoint_name, "-o", "json"],
        capture_output=True, text=True, shell=IS_WINDOWS,
    )
    key = ""
    if key_result.returncode == 0:
        try:
            credentials = json.loads(key_result.stdout)
            key = (
                credentials.get("primaryKey")
                or credentials.get("primary_key")
                or credentials.get("key")
                or ""
            )
        except json.JSONDecodeError:
            log.warning("Could not parse serverless endpoint credentials JSON")
    if not key:
        log.warning("No key returned for serverless endpoint '%s'", endpoint_name)

    # Extract model name from model_id
    model_name = model_id.split("/")[-1] if "/" in model_id else model_id

    console.print(f"  [green]Endpoint '{endpoint_name}' ready: {uri}[/green]")
    emit_progress(
        f"Foundry model deployed: {model_name}",
        stage="index.deploy_model", model_name=model_name, uri=uri,
    )

    return {"uri": uri, "key": key, "model_name": model_name}


def _get_storage_resource_id(resource_group: str, storage_account: str) -> str:
    """Get the full ARM resource ID for a storage account via az CLI."""
    cmd = [
        "az", "storage", "account", "show",
        "-g", resource_group, "-n", storage_account,
        "--query", "id", "-o", "tsv",
    ]
    result = subprocess.run(cmd, capture_output=True, text=True, shell=IS_WINDOWS)
    if result.returncode != 0:
        raise RuntimeError(f"Failed to get storage resource ID: {result.stderr.strip()}")
    return result.stdout.strip()


# ── Multi-vector (BGE-M3 via Foundry managed compute) ────────────────


def create_multivector_index(
    endpoint: str,
    index_name: str,
    ai_services_endpoint: str,
    embedding_model: str = "text-embedding-3-large",
    storage_account: str = "",
    resource_group: str = "",
    container: str = "corpus",
    cohere_uri: str = "",
    cohere_model_name: str = "",
    cohere_key: str = "",
    custom_embedding_uri: str = "",
    custom_embedding_key: str = "",
    custom_embedding_dimensions: int = 0,
    custom_embedding_header_name: str = "api-key",
):
    """Create a multi-vector index with dense + sparse fields.

    When cohere_uri is provided, uses AML skill + AML vectorizer for the
    Cohere Foundry catalog integration. When custom_embedding_uri is provided,
    uses Custom Web API skill + vectorizer for any embedding endpoint that speaks
    the Azure AI Search custom skill/vectorizer contract. Otherwise falls back
    to AzureOpenAI embedding with an additional sparse BM25 field.

    Per MS docs: Foundry catalog vectorization supports Cohere models through
    `kind: aml`; non-Cohere models should use `kind: customWebApi`.
    """
    credential = DefaultAzureCredential()
    index_client = SearchIndexClient(endpoint, credential)
    indexer_client = SearchIndexerClient(endpoint, credential)

    console.print(f"  [cyan]multi-vector[/cyan]: creating index '{index_name}'...")

    storage_resource_id = ""
    if storage_account and resource_group:
        storage_resource_id = _get_storage_resource_id(resource_group, storage_account)

    if cohere_uri and custom_embedding_uri:
        raise ValueError("Use either cohere_uri or custom_embedding_uri, not both")
    if cohere_uri:
        dims = _embedding_dimensions(embedding_model, cohere_model_name)
        if not cohere_model_name:
            raise ValueError("cohere_model_name is required when cohere_uri is provided")
        if not cohere_key:
            raise ValueError(
                "cohere_key is required for Cohere Foundry model catalog integration; "
                "Azure AI Search doesn't support token auth for Cohere models."
            )
    elif custom_embedding_uri:
        dims = _custom_embedding_dimensions(embedding_model, custom_embedding_dimensions)
    else:
        dims = _embedding_dimensions(embedding_model)

    # Data source
    ds = SearchIndexerDataSourceConnection(
        name=f"{index_name}-ds",
        type="azureblob",
        connection_string=f"ResourceId={storage_resource_id};",
        container=SearchIndexerDataContainer(name=container),
    )
    indexer_client.create_or_update_data_source_connection(ds)

    # Index with multiple vector fields
    fields = [
        SearchField(name="id", type=SearchFieldDataType.String, key=True,
                    filterable=True, analyzer_name="keyword"),
        SearchField(name="parent_id", type=SearchFieldDataType.String, filterable=True),
        SearchField(name="content", type=SearchFieldDataType.String, searchable=True),
        SearchField(
            name="title",
            type=SearchFieldDataType.String,
            searchable=True,
            filterable=True,
        ),
        SearchField(name="doc_id", type=SearchFieldDataType.String,
                    filterable=True, searchable=True, sortable=True),
        SearchField(name="metadata_storage_name", type=SearchFieldDataType.String, filterable=True),
        # Dense vector from AzureOpenAI or Foundry catalog model
        SearchField(
            name="content_vector",
            type=SearchFieldDataType.Collection(SearchFieldDataType.Single),
            searchable=True,
            vector_search_dimensions=dims,
            vector_search_profile_name="dense-profile",
        ),
    ]

    semantic_search = SemanticSearch(
        configurations=[
            SemanticConfiguration(
                name="default-semantic",
                prioritized_fields=SemanticPrioritizedFields(
                    title_field=SemanticField(field_name="title"),
                    content_fields=[SemanticField(field_name="content")],
                ),
            )
        ],
    )

    if cohere_uri or custom_embedding_uri:
        if cohere_uri:
            vectorizer_name = "aml-vectorizer"
            vectorizer = {
                "name": vectorizer_name,
                "kind": "aml",
                "amlParameters": {
                    "uri": cohere_uri.rstrip("/"),
                    "key": cohere_key,
                    "modelName": cohere_model_name,
                    "timeout": "PT60S",
                },
            }
        else:
            vectorizer_name = "custom-web-api-vectorizer"
            headers = (
                {custom_embedding_header_name: custom_embedding_key}
                if custom_embedding_key else {}
            )
            vectorizer = {
                "name": vectorizer_name,
                "kind": "customWebApi",
                "customWebApiParameters": {
                    "uri": custom_embedding_uri,
                    "httpMethod": "POST",
                    "httpHeaders": headers,
                    "timeout": "PT60S",
                },
            }

        index_payload = {
            "name": index_name,
            "fields": _serialized_fields(fields),
            "semantic": semantic_search.serialize(),
            "vectorSearch": {
                "algorithms": [
                    {
                        "name": "hnsw-config",
                        "kind": "hnsw",
                        "hnswParameters": {
                            "m": 8,
                            "efConstruction": 800,
                            "efSearch": 500,
                            "metric": "cosine",
                        },
                    }
                ],
                "profiles": [
                    {
                        "name": "dense-profile",
                        "algorithm": "hnsw-config",
                        "vectorizer": vectorizer_name,
                    }
                ],
                "vectorizers": [vectorizer],
            },
        }
        _put_search_resource(endpoint, f"indexes/{index_name}", index_payload, credential)
    else:
        from azure.search.documents.indexes.models import (
            AzureOpenAIVectorizer,
            AzureOpenAIVectorizerParameters,
        )

        vectorizers = [
            AzureOpenAIVectorizer(
                vectorizer_name="openai-vectorizer",
                parameters=AzureOpenAIVectorizerParameters(
                    resource_url=ai_services_endpoint,
                    deployment_name=embedding_model,
                    model_name=embedding_model,
                ),
            )
        ]

        vector_search = VectorSearch(
            algorithms=[
                HnswAlgorithmConfiguration(
                    name="hnsw-config",
                    parameters=HnswParameters(
                        m=8, ef_construction=800, ef_search=500, metric="cosine"
                    ),
                )
            ],
            profiles=[
                VectorSearchProfile(
                    name="dense-profile",
                    algorithm_configuration_name="hnsw-config",
                    vectorizer_name="openai-vectorizer",
                ),
            ],
            vectorizers=vectorizers,
        )

        index = SearchIndex(name=index_name, fields=fields, vector_search=vector_search)
        index.semantic_search = semantic_search
        index_client.create_or_update_index(index)

    # Skillset — use AML for Cohere, Custom Web API for arbitrary embeddings,
    # or AzureOpenAI for the default path.
    from azure.search.documents.indexes.models import AzureOpenAIEmbeddingSkill

    if cohere_uri:
        # AML skill for Foundry catalog model (Cohere)
        # Per MS docs: must append /v1/embed to URI for Cohere skill
        skill_uri = cohere_uri.rstrip("/") + "/v1/embed"
        skills_list: list[Any] = [
            SplitSkill(
                name="chunk-skill",
                text_split_mode="pages",
                maximum_page_length=2000,
                page_overlap_length=500,
                inputs=[InputFieldMappingEntry(name="text", source="/document/content")],
                outputs=[OutputFieldMappingEntry(name="textItems", target_name="chunks")],
            ),
            # AML skill definition per MS docs
            {
                "@odata.type": "#Microsoft.Skills.Custom.AmlSkill",
                "name": "cohere-embed-skill",
                "context": "/document/chunks/*",
                "uri": skill_uri,
                "key": cohere_key,
                "timeout": "PT60S",
                "inputs": [
                    {"name": "texts", "source": "=[$(/document/chunks/*)]"},
                    {"name": "input_type", "source": "='search_document'"},
                    {"name": "truncate", "source": "='NONE'"},
                    {"name": "embedding_types", "source": "=['float']"},
                ],
                "outputs": [
                    {"name": "embeddings", "targetName": "aml_vector_data"},
                ],
            },
        ]
        # For Cohere: output path is /document/chunks/*/aml_vector_data/float/0
        vector_mapping_source = "/document/chunks/*/aml_vector_data/float/0"
    elif custom_embedding_uri:
        headers = (
            {custom_embedding_header_name: custom_embedding_key}
            if custom_embedding_key else {}
        )
        skills_list = [
            SplitSkill(
                name="chunk-skill",
                text_split_mode="pages",
                maximum_page_length=2000,
                page_overlap_length=500,
                inputs=[InputFieldMappingEntry(name="text", source="/document/content")],
                outputs=[OutputFieldMappingEntry(name="textItems", target_name="chunks")],
            ),
            {
                "@odata.type": "#Microsoft.Skills.Custom.WebApiSkill",
                "name": "custom-embed-skill",
                "context": "/document/chunks/*",
                "uri": custom_embedding_uri,
                "httpMethod": "POST",
                "httpHeaders": headers,
                "timeout": "PT60S",
                "batchSize": 16,
                "inputs": [
                    {"name": "text", "source": "/document/chunks/*"},
                ],
                "outputs": [
                    {"name": "vector", "targetName": "content_vector"},
                ],
            },
        ]
        vector_mapping_source = "/document/chunks/*/content_vector"
    else:
        skills_list = [
            SplitSkill(
                name="chunk-skill",
                text_split_mode="pages",
                maximum_page_length=2000,
                page_overlap_length=500,
                inputs=[InputFieldMappingEntry(name="text", source="/document/content")],
                outputs=[OutputFieldMappingEntry(name="textItems", target_name="chunks")],
            ),
            AzureOpenAIEmbeddingSkill(
                name="embed-skill",
                context="/document/chunks/*",
                resource_url=ai_services_endpoint,
                deployment_name=embedding_model,
                model_name=embedding_model,
                dimensions=dims,
                inputs=[InputFieldMappingEntry(name="text", source="/document/chunks/*")],
                outputs=[OutputFieldMappingEntry(name="embedding", target_name="content_vector")],
            ),
        ]
        vector_mapping_source = "/document/chunks/*/content_vector"

    index_projection = SearchIndexerIndexProjection(
        selectors=[
            SearchIndexerIndexProjectionSelector(
                target_index_name=index_name,
                parent_key_field_name="parent_id",
                source_context="/document/chunks/*",
                mappings=[
                    InputFieldMappingEntry(name="content", source="/document/chunks/*"),
                    InputFieldMappingEntry(name="content_vector", source=vector_mapping_source),
                    InputFieldMappingEntry(name="title", source="/document/metadata_storage_name"),
                    InputFieldMappingEntry(
                        name="metadata_storage_name",
                        source="/document/metadata_storage_name",
                    ),
                    InputFieldMappingEntry(name="doc_id", source="/document/metadata_storage_name"),
                ],
            )
        ],
        parameters=SearchIndexerIndexProjectionsParameters(
            projection_mode="skipIndexingParentDocuments",
        ),
    )

    if cohere_uri or custom_embedding_uri:
        skillset_payload = {
            "name": f"{index_name}-skillset",
            "skills": [
                skill.serialize() if hasattr(skill, "serialize") else skill for skill in skills_list
            ],
            "indexProjections": index_projection.serialize(),
        }
        _put_search_resource(
            endpoint,
            f"skillsets/{index_name}-skillset",
            skillset_payload,
            credential,
        )
    else:
        skillset = SearchIndexerSkillset(
            name=f"{index_name}-skillset",
            skills=skills_list,
            index_projection=index_projection,
        )
        indexer_client.create_or_update_skillset(skillset)

    # Indexer
    indexer = SearchIndexer(
        name=f"{index_name}-indexer",
        data_source_name=f"{index_name}-ds",
        target_index_name=index_name,
        skillset_name=f"{index_name}-skillset",
        parameters={
            "configuration": {
                "parsingMode": "markdown",
                "markdownParsingSubmode": "oneToMany",
                "dataToExtract": "contentAndMetadata",
            },
        },
    )
    indexer_client.create_or_update_indexer(indexer)
    try:
        indexer_client.run_indexer(f"{index_name}-indexer")
    except Exception as e:
        if "concurrent" in str(e).lower() or "in progress" in str(e).lower():
            pass
        else:
            raise

    console.print("  [green]multi-vector[/green] index + skillset + indexer created and running")
    emit_progress(
        f"multi-vector index '{index_name}' created",
        stage="search_index.create", architecture="multi-vector", index_name=index_name,
    )


# ── Agentic Retrieval (Knowledge Bases) ──────────────────────────────


def create_agentic_kb(
    endpoint: str,
    index_name: str,
    ai_services_endpoint: str,
    kb_name: str = "",
    llm_deployment: str = "gpt-4.1",
    llm_model: str = "gpt-4.1",
):
    """Create a Knowledge Base on top of an existing search index.

    Per MS docs (2026-04-01 GA API):
    1. Create SearchIndexKnowledgeSource pointing to the existing index
    2. Create KnowledgeBase referencing the source + LLM model
    3. Query via KnowledgeBaseRetrievalClient

    The underlying search index must already exist (typically hybrid-reranker).
    """
    credential = DefaultAzureCredential()

    if not kb_name:
        kb_name = f"{index_name}-kb"

    ks_name = f"{index_name}-ks"

    console.print(f"  [cyan]agentic-kb[/cyan]: creating knowledge source '{ks_name}'...")

    knowledge_source = {
        "name": ks_name,
        "kind": "searchIndex",
        "description": f"Knowledge source for {index_name}",
        "searchIndexParameters": {
            "searchIndexName": index_name,
            "semanticConfigurationName": "default-semantic",
            "sourceDataFields": [
                {"name": "content"},
                {"name": "title"},
                {"name": "doc_id"},
            ],
            "searchFields": [{"name": "content"}],
        },
    }
    _put_search_resource(
        endpoint,
        f"knowledgesources('{quote(ks_name, safe='')}')",
        knowledge_source,
        credential,
        api_version=SEARCH_AGENTIC_API_VERSION,
    )
    console.print(f"  [green]Knowledge source '{ks_name}' created[/green]")

    # 2. Create Knowledge Base with LLM model
    console.print(f"  [cyan]agentic-kb[/cyan]: creating knowledge base '{kb_name}'...")

    knowledge_base = {
        "name": kb_name,
        "description": f"Agentic retrieval knowledge base for {index_name}",
        "retrievalInstructions": (
            "Use the knowledge source to answer questions about policies and procedures."
        ),
        "outputMode": "extractiveData",
        "retrievalReasoningEffort": {"kind": "low"},
        "knowledgeSources": [{"name": ks_name}],
        "models": [
            {
                "kind": "azureOpenAI",
                "azureOpenAIParameters": {
                    "resourceUri": ai_services_endpoint,
                    "deploymentId": llm_deployment,
                    "modelName": llm_model,
                },
            }
        ],
    }
    _put_search_resource(
        endpoint,
        f"knowledgebases('{quote(kb_name, safe='')}')",
        knowledge_base,
        credential,
        api_version=SEARCH_AGENTIC_API_VERSION,
    )

    console.print(f"  [green]Knowledge base '{kb_name}' created[/green]")
    emit_progress(
        f"agentic-kb '{kb_name}' created",
        stage="search_index.create", architecture="agentic-kb", kb_name=kb_name,
    )

    return {"kb_name": kb_name, "ks_name": ks_name}


# ── Agentic KB query adapter ─────────────────────────────────────────


def query_agentic_kb(
    endpoint: str,
    kb_name: str,
    query: str,
    top_k: int = 10,
) -> tuple[list[str], float]:
    """Query an Azure AI Search Knowledge Base.

    Uses KnowledgeBaseRetrievalClient for agentic multi-hop retrieval.
    Returns (chunk_ids, latency_ms).
    """
    credential = DefaultAzureCredential()

    try:
        from azure.search.documents.knowledgebases import KnowledgeBaseRetrievalClient
        from azure.search.documents.knowledgebases.models import (
            KnowledgeBaseMessage,
            KnowledgeBaseMessageTextContent,
            KnowledgeBaseRetrievalRequest,
        )
    except ModuleNotFoundError:
        log.warning(
            "Azure Search KnowledgeBase SDK is not installed; falling back to base index query"
        )
        return _query_agentic_kb_base_index(endpoint, kb_name, query, top_k, credential)

    kb_client = KnowledgeBaseRetrievalClient(
        endpoint=endpoint,
        knowledge_base_name=kb_name,
        credential=credential,
    )

    request = KnowledgeBaseRetrievalRequest(
        messages=[
            KnowledgeBaseMessage(
                role="user",
                content=[KnowledgeBaseMessageTextContent(text=query)],
            ),
        ],
    )

    import time as _time
    start = _time.perf_counter()
    try:
        result = kb_client.retrieve(retrieval_request=request)
        latency_ms = (_time.perf_counter() - start) * 1000

        # Extract references from response
        chunk_ids = []
        if result.response:
            for resp in result.response:
                if hasattr(resp, "content") and resp.content:
                    for content_item in resp.content:
                        text = getattr(content_item, "text", "")
                        # Extract ref_ids from response text
                        import re
                        refs = re.findall(r'\[ref_id:(\d+)\]', text)
                        chunk_ids.extend(refs)
                # Extract from references if available
                if hasattr(result, "references") and result.references:
                    for ref in result.references:
                        ref_data = getattr(ref, "source_data", {}) or {}
                        doc_id = ref_data.get("doc_id", "") or ref_data.get("title", "")
                        if doc_id:
                            chunk_ids.append(str(doc_id))

        return chunk_ids[:top_k], latency_ms
    except Exception as e:
        latency_ms = (_time.perf_counter() - start) * 1000
        log.warning("Agentic KB query failed: %s", e)
        return [], latency_ms


def _query_agentic_kb_base_index(
    endpoint: str,
    kb_name: str,
    query: str,
    top_k: int,
    credential: DefaultAzureCredential,
) -> tuple[list[str], float]:
    import time as _time

    from azure.search.documents import SearchClient
    from azure.search.documents.models import VectorizableTextQuery

    index_name = kb_name if kb_name.endswith("-base") else f"{kb_name}-base"
    client = SearchClient(endpoint, index_name, credential)
    start = _time.perf_counter()
    results = client.search(
        search_text=query,
        vector_queries=[
            VectorizableTextQuery(
                text=query,
                k_nearest_neighbors=50,
                fields="content_vector",
            )
        ],
        top=top_k,
        scoring_statistics="global",
    )
    chunk_ids: list[str] = []
    for result in results:
        chunk_id = result.get("chunk_id") or result.get("id") or result.get("metadata_storage_name")
        if chunk_id:
            chunk_ids.append(str(chunk_id))
    latency_ms = (_time.perf_counter() - start) * 1000
    return chunk_ids[:top_k], latency_ms


# ── GraphRAG indexing ─────────────────────────────────────────────────


def run_graphrag_indexing(
    corpus_dir: str,
    ai_services_endpoint: str,
    search_endpoint: str = "",
    storage_account: str = "",
    cosmos_endpoint: str = "",
    function_endpoint: str = "",
    graph_worker_endpoint: str = "",
    embedding_model: str = "text-embedding-3-large",
    llm_model: str = "gpt-4.1",
    output_dir: str = ".graphrag",
    method: str = "fast",
    run_scope: GraphRagRunScope = "sample",
    max_documents: int | None = 50,
):
    """Run GraphRAG indexing pipeline on the corpus.

    Uses the `graphrag` Python package to:
    1. Initialize a GraphRAG project
    2. Configure Azure OpenAI as the LLM/embedding provider
    3. Run entity extraction, community detection, embedding
    4. Store artifacts in local output dir (or Cosmos DB if configured)

    Requires: pip install graphrag
    """
    validate_graphrag_run_scope(run_scope, max_documents)
    corpus_manifest = load_corpus_manifest(corpus_dir)
    corpus_fingerprint = str(corpus_manifest["corpus_fingerprint"])

    if graph_worker_endpoint:
        console.print("  [cyan]graphrag[/cyan]: requesting cloud container indexing...")
        response = requests.post(
            f"{graph_worker_endpoint.rstrip('/')}/index",
            json={
                "storage_account": storage_account,
                "corpus_container": "corpus",
                "corpus_prefix": "",
                "output_container": "graphrag",
                "method": method,
                "run_scope": run_scope,
                "max_documents": max_documents,
                "corpus_fingerprint": corpus_fingerprint,
                "ai_services_endpoint": ai_services_endpoint,
                "search_endpoint": search_endpoint,
                "llm_model": llm_model,
                "embedding_model": embedding_model,
            },
            timeout=(10, 120),
        )
        response.raise_for_status()
        job_id = str(response.json().get("job_id", ""))
        if not job_id:
            raise RuntimeError("GraphRAG worker did not return a job_id")

        status_url = f"{graph_worker_endpoint.rstrip('/')}/index/{job_id}/status"
        estimate = "20-90 minutes for large corpora; refresh architecture status to check progress"
        console.print(
            f"  [green]GraphRAG cloud indexing started[/green] "
            f"(job {job_id}). Estimate: {estimate}."
        )
        emit_progress(
            f"GraphRAG cloud indexing started ({estimate})",
            stage="index.graphrag.started",
            job_id=job_id,
            status_url=status_url,
            estimated_duration=estimate,
        )
        return {
            "cloud_index_status": "started",
            "graph_worker_job_id": job_id,
            "graph_worker_status_url": status_url,
            "graph_worker_artifact_prefix": (
                f"runs/{corpus_fingerprint}/{job_id}"
            ),
            "corpus_fingerprint": corpus_fingerprint,
            "graph_worker_run_scope": run_scope,
            "graph_worker_max_documents": max_documents,
            "graph_worker_estimate": estimate,
        }

    if function_endpoint:
        raise RuntimeError(
            "GraphRAG Function endpoint is deprecated for indexing. Configure a "
            "GraphRAG worker container endpoint instead."
        )

    if run_scope != "full":
        raise RuntimeError(
            "Capped GraphRAG sample/canary runs require the cloud worker so the "
            "document limit is enforced before indexing."
        )

    if os.environ.get("RETRIEVE_ALLOW_LOCAL_GRAPHRAG", "").lower() not in {"1", "true", "yes"}:
        raise RuntimeError(
            "GraphRAG cloud worker endpoint is not configured. Local GraphRAG indexing is disabled "
            "by default; set RETRIEVE_ALLOW_LOCAL_GRAPHRAG=1 only for local development."
        )

    console.print(
        "  [yellow]Using local GraphRAG indexing because "
        "RETRIEVE_ALLOW_LOCAL_GRAPHRAG is set.[/yellow]"
    )

    if not importlib.util.find_spec("graphrag"):
        console.print(
            "graphrag package not installed. Run: pip install 'retrieve[graphrag]'",
            style="red",
            markup=False,
        )
        return

    from pathlib import Path

    import yaml

    output_path = Path(output_dir)
    output_path.mkdir(parents=True, exist_ok=True)
    corpus_path = Path(corpus_dir).resolve()

    local_run_id = uuid.uuid4().hex
    settings = build_graphrag_settings(
        input_dir=corpus_path,
        ai_services_endpoint=ai_services_endpoint,
        llm_model=llm_model,
        embedding_model=embedding_model,
        method=method,
        storage_account_blob_url=(
            f"https://{storage_account}.blob.core.windows.net"
            if storage_account
            else ""
        ),
        storage_container="graphrag",
        run_prefix=f"runs/{corpus_fingerprint}/{local_run_id}",
        cache_prefix=f"cache/{corpus_fingerprint}",
        search_endpoint=search_endpoint,
        vector_index_prefix=f"gr-{corpus_fingerprint[:8]}-{local_run_id[:8]}",
    )
    config = validate_graphrag_settings(settings)

    if cosmos_endpoint:
        console.print(
            "  [yellow]GraphRAG Cosmos is not used by the pinned GraphRAG 3.1 "
            "Blob/Search storage path.[/yellow]"
        )

    settings_file = output_path / "settings.yaml"
    settings_file.write_text(yaml.dump(settings, default_flow_style=False), encoding="utf-8")

    console.print("  [cyan]graphrag[/cyan]: running indexing pipeline...")
    console.print(f"  Input: {corpus_dir}")
    console.print(f"  Output: {output_path}")

    from graphrag.api import build_index

    results = asyncio.run(build_index(config=config, method=method))
    failures = [result for result in results if result.error is not None]
    if failures:
        details = "; ".join(
            f"{result.workflow}: {result.error}" for result in failures
        )
        raise RuntimeError(f"GraphRAG workflows failed: {details}")

    console.print("  [green]GraphRAG indexing complete[/green]")
    emit_progress("GraphRAG indexing complete", stage="index.graphrag")


def query_graphrag(
    query: str,
    mode: str = "local",
    output_dir: str = ".graphrag",
    corpus_dir: str = "corpus",
    ai_services_endpoint: str = "",
    function_endpoint: str = "",
    graph_worker_endpoint: str = "",
    artifact_prefix: str = "",
    corpus_fingerprint: str = "",
) -> tuple[list[str], float]:
    """Query GraphRAG and return canonical document IDs plus latency."""
    import time as _time
    start = _time.perf_counter()

    if function_endpoint:
        raise RuntimeError(
            "GraphRAG Function query endpoints are unsupported. Use the internal "
            "GraphRAG worker or the public local API adapter."
        )

    if graph_worker_endpoint:
        if not artifact_prefix or not corpus_fingerprint:
            raise RuntimeError(
                "GraphRAG worker queries require an immutable artifact prefix and "
                "corpus fingerprint"
            )
        response = requests.post(
            f"{graph_worker_endpoint.rstrip('/')}/query",
            json={
                "artifact_prefix": artifact_prefix,
                "corpus_fingerprint": corpus_fingerprint,
                "query": query,
                "mode": mode,
            },
            timeout=(10, 180),
        )
        response.raise_for_status()
        data = response.json()
        document_ids = data.get("document_ids")
        if not isinstance(document_ids, list):
            raise RuntimeError("GraphRAG worker returned invalid structured evidence")
        latency_ms = (_time.perf_counter() - start) * 1000
        return [str(document_id) for document_id in document_ids], latency_ms

    from pathlib import Path

    import yaml

    from retrieve.graphrag.query import execute_graphrag_query

    settings_file = Path(output_dir) / "settings.yaml"
    if not settings_file.is_file():
        raise RuntimeError(f"GraphRAG settings not found: {settings_file}")
    settings = yaml.safe_load(settings_file.read_text(encoding="utf-8"))
    if not isinstance(settings, dict):
        raise RuntimeError("GraphRAG settings must be a YAML mapping")
    config = validate_graphrag_settings(settings)
    manifest = load_corpus_manifest(corpus_dir)
    result = asyncio.run(
        execute_graphrag_query(
            config=config,
            corpus_manifest=manifest,
            query=query,
            mode=mode,
        )
    )
    latency_ms = (_time.perf_counter() - start) * 1000
    return list(result.document_ids), latency_ms


# ── LightRAG indexing ─────────────────────────────────────────────────


def run_lightrag_indexing(
    corpus_dir: str,
    ai_services_endpoint: str,
    container_app_endpoint: str = "",
    embedding_model: str = "text-embedding-3-large",
    llm_model: str = "gpt-4.1",
    working_dir: str = ".lightrag",
):
    """Run LightRAG indexing on the corpus.

    Uses the `lightrag-hku` package to build a lightweight knowledge graph.
    Requires: pip install lightrag-hku
    """
    from pathlib import Path

    corpus_path = Path(corpus_dir)
    md_files = list(corpus_path.glob("**/*.md"))

    if container_app_endpoint:
        unique_documents: list[tuple[str, str]] = []
        seen_hashes: set[str] = set()
        duplicate_count = 0
        for md_file in md_files:
            content = md_file.read_text(encoding="utf-8")
            if content.startswith("---"):
                end = content.find("---", 3)
                if end > 0:
                    content = content[end + 3:].strip()
            content_hash = hashlib.sha256(content.encode("utf-8")).hexdigest()
            if content_hash in seen_hashes:
                duplicate_count += 1
                continue
            seen_hashes.add(content_hash)
            source = str(md_file.relative_to(corpus_path)).replace("\\", "/")
            unique_documents.append((content, source))

        if duplicate_count:
            console.print(
                f"  [yellow]lightrag[/yellow]: skipped {duplicate_count} duplicate "
                "documents by content hash"
            )
            emit_progress(
                f"LightRAG skipped {duplicate_count} duplicate documents",
                stage="index.lightrag.dedupe",
                duplicate_count=duplicate_count,
            )

        console.print(
            f"  [cyan]lightrag[/cyan]: sending {len(unique_documents)} unique documents to cloud "
            "Container App..."
        )
        batch_size = 50
        track_ids: list[str] = []
        for start in range(0, len(unique_documents), batch_size):
            batch = unique_documents[start:start + batch_size]
            texts = [content for content, _source in batch]
            sources = [source for _content, source in batch]
            response = call_with_backoff(
                lambda: requests.post(
                    f"{container_app_endpoint.rstrip('/')}/documents/texts",
                    json={"texts": texts, "file_sources": sources},
                    timeout=(10, 120),
                ),
                policy=BackoffPolicy.from_env(
                    "RETRIEVE_HTTP_BACKOFF",
                    max_attempts=6,
                    base_delay_seconds=5.0,
                    max_delay_seconds=60.0,
                ),
                operation="LightRAG document batch submit",
                logger=log,
                retry_exceptions=(requests.RequestException,),
                should_retry_result=is_retryable_http_response,
            )
            response.raise_for_status()
            data = response.json()
            track_id = str(data.get("track_id", ""))
            if track_id:
                track_ids.append(track_id)
            completed = min(start + len(batch), len(unique_documents))
            console.print(f"  Sent {completed}/{len(unique_documents)} documents to LightRAG cloud")
            emit_progress(
                f"LightRAG cloud insert {completed}/{len(unique_documents)}",
                stage="index.lightrag", completed=completed, total=len(unique_documents),
            )
        console.print(
            f"  [green]LightRAG cloud indexing requested "
            f"({len(track_ids)} batches)[/green]"
        )
        estimate = (
            "10-60 minutes after batches are accepted; "
            "refresh architecture status to check progress"
        )
        emit_progress(
            f"LightRAG cloud indexing started ({estimate})",
            stage="index.lightrag.started",
            track_count=len(track_ids),
            estimated_duration=estimate,
        )
        return {
            "cloud_index_status": "started",
            "lightrag_track_ids": track_ids,
            "lightrag_track_count": len(track_ids),
            "lightrag_estimate": estimate,
        }

    try:
        from lightrag import LightRAG
        from lightrag.llm.azure_openai import azure_openai_complete, azure_openai_embedding
    except ImportError:
        console.print(
            "lightrag-hku not installed. Run: pip install 'retrieve[lightrag]'",
            style="red",
            markup=False,
        )
        return

    import asyncio

    work_path = Path(working_dir)
    work_path.mkdir(parents=True, exist_ok=True)

    console.print("  [cyan]lightrag[/cyan]: initializing with Azure OpenAI...")

    # Initialize LightRAG with Azure OpenAI
    rag = LightRAG(
        working_dir=str(work_path),
        llm_model_func=azure_openai_complete,
        llm_model_name=llm_model,
        llm_model_kwargs={
            "api_base": ai_services_endpoint,
            "api_version": "2025-04-01-preview",
        },
        embedding_func=azure_openai_embedding,
        embedding_model_name=embedding_model,
        embedding_model_kwargs={
            "api_base": ai_services_endpoint,
            "api_version": "2025-04-01-preview",
        },
    )

    # Read and insert all corpus documents
    console.print(f"  Inserting {len(md_files)} documents into LightRAG...")

    for i, md_file in enumerate(md_files):
        content = md_file.read_text(encoding="utf-8")
        # Skip YAML frontmatter
        if content.startswith("---"):
            end = content.find("---", 3)
            if end > 0:
                content = content[end + 3:].strip()

        try:
            asyncio.run(rag.ainsert(content))
        except Exception as e:
            log.warning("Failed to insert %s: %s", md_file.name, e)

        if (i + 1) % 10 == 0:
            console.print(f"  Inserted {i + 1}/{len(md_files)} documents")
            emit_progress(
                f"LightRAG insert {i + 1}/{len(md_files)}",
                stage="index.lightrag", completed=i + 1, total=len(md_files),
            )

    console.print(f"  [green]LightRAG indexing complete ({len(md_files)} documents)[/green]")
    emit_progress("LightRAG indexing complete", stage="index.lightrag")


def query_lightrag(
    query: str,
    mode: str = "mix",
    working_dir: str = ".lightrag",
    ai_services_endpoint: str = "",
    container_app_endpoint: str = "",
) -> tuple[list[str], float]:
    """Query a LightRAG index.

    Supports local (Python-based) or remote (Container Apps endpoint) querying.
    mode: naive, local, global, hybrid, mix
    Returns (chunk_ids, latency_ms).
    """
    import time as _time
    start = _time.perf_counter()

    # If container app endpoint is available, use it
    if container_app_endpoint:
        import requests
        try:
            resp = requests.post(
                f"{container_app_endpoint}/query",
                json={"query": query, "mode": mode},
                timeout=60,
            )
            resp.raise_for_status()
            data = resp.json()
            latency_ms = (_time.perf_counter() - start) * 1000
            return data.get("chunk_ids", data.get("response", "").split("\n")[:10]), latency_ms
        except Exception as e:
            log.warning("LightRAG remote query failed: %s", e)
            latency_ms = (_time.perf_counter() - start) * 1000
            return [], latency_ms

    # Local query
    try:
        from lightrag import LightRAG, QueryParam
        from lightrag.llm.azure_openai import azure_openai_complete, azure_openai_embedding

        rag = LightRAG(
            working_dir=working_dir,
            llm_model_func=azure_openai_complete,
            embedding_func=azure_openai_embedding,
        )

        import asyncio
        result = asyncio.run(rag.aquery(query, param=QueryParam(mode=mode)))
        latency_ms = (_time.perf_counter() - start) * 1000
        # Extract doc references from response
        chunk_ids = [line[:100] for line in str(result).split("\n") if line.strip()][:10]
        return chunk_ids, latency_ms
    except Exception as e:
        latency_ms = (_time.perf_counter() - start) * 1000
        log.warning("LightRAG local query failed: %s", e)
        return [], latency_ms
