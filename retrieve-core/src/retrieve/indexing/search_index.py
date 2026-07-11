"""Search index builder per Azure AI Search, indexer pipeline, and Foundry guidance.

Auth: DefaultAzureCredential for all operations  no admin keys.
Data source: ResourceId connection string (managed identity, no storage keys).
Index creation: Python SDK classes (SearchIndex, VectorSearch, AzureOpenAIVectorizer, etc.)
Skillset: Python SDK (SearchIndexerSkillset, AzureOpenAIEmbeddingSkill)

Per architecture:
- keyword: text fields only, markdown oneToMany parsing
- hybrid: text + vector fields, SplitSkill + AzureOpenAIEmbeddingSkill + index projections
- hybrid-reranker: hybrid + SemanticConfiguration

Keyword indexes use markdown oneToMany parsing for heading-aligned chunking.
Vector indexes use the supported SplitSkill + projection pipeline for chunked embeddings.

Guardrail: large text fields must not be marked filterable, facetable, or sortable.
Azure AI Search treats those modes as whole-term indexing, which hits the 32 KB
(32766-byte UTF-8 term) limit on long policy sections. If field-level toggles are
added later, the UI/config layer should either block those combinations for long-text
fields or automatically chunk/project that content into safer fields.
"""

from __future__ import annotations

import logging
import subprocess
import sys
import time
from urllib.parse import quote

import requests
from azure.identity import DefaultAzureCredential
from azure.search.documents.indexes import SearchIndexClient, SearchIndexerClient
from azure.search.documents.indexes.models import (
    AzureOpenAIEmbeddingSkill,
    AzureOpenAIVectorizer,
    AzureOpenAIVectorizerParameters,
    HnswAlgorithmConfiguration,
    HnswParameters,
    InputFieldMappingEntry,
    OutputFieldMappingEntry,
    SearchableField,
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
    SimpleField,
    SplitSkill,
    VectorSearch,
    VectorSearchProfile,
)
from rich.console import Console

from retrieve.observability import emit_progress

log = logging.getLogger(__name__)
console = Console()

IS_WINDOWS = sys.platform == "win32"
SEARCH_API_VERSION = "2024-07-01"


def _search_rest_headers(credential: DefaultAzureCredential) -> dict[str, str]:
    token = credential.get_token("https://search.azure.com/.default").token
    return {"Authorization": f"Bearer {token}", "Content-Type": "application/json"}


def _search_rest_get(
    endpoint: str,
    path: str,
    credential: DefaultAzureCredential,
    timeout: tuple[int, int] = (10, 30),
) -> dict:
    separator = "&" if "?" in path else "?"
    url = f"{endpoint.rstrip('/')}/{path.lstrip('/')}{separator}api-version={SEARCH_API_VERSION}"
    response = requests.get(
        url,
        headers=_search_rest_headers(credential),
        timeout=timeout,
    )
    response.raise_for_status()
    return response.json()


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


def create_index_for_architecture(
    arch_name: str,
    endpoint: str,
    index_name: str,
    ai_services_endpoint: str = "",
    embedding_model: str = "text-embedding-3-large",
    storage_account: str = "",
    resource_group: str = "",
    container: str = "corpus",
    # Advanced architecture options
    cosmos_endpoint: str = "",
    function_endpoint: str = "",
    graph_worker_endpoint: str = "",
    container_app_endpoint: str = "",
    corpus_dir: str = "",
    llm_model: str = "gpt-4.1",
    cohere_uri: str = "",
    cohere_model_name: str = "",
    cohere_key: str = "",
    custom_embedding_uri: str = "",
    custom_embedding_key: str = "",
    custom_embedding_dimensions: int = 0,
    custom_embedding_header_name: str = "api-key",
):
    """Create the appropriate search index for a given architecture.

    Uses DefaultAzureCredential  requires Search Service Contributor role.
    Data source uses ResourceId connection  requires Search -> Blob Data Reader role.
    """
    credential = DefaultAzureCredential()
    index_client = SearchIndexClient(endpoint, credential)
    indexer_client = SearchIndexerClient(endpoint, credential)

    storage_resource_id = ""
    if storage_account and resource_group:
        storage_resource_id = _get_storage_resource_id(resource_group, storage_account)

    if arch_name == "keyword":
        _create_keyword_index(
            indexer_client,
            index_client,
            index_name,
            storage_resource_id,
            container,
        )
    elif arch_name in ("single-vector", "hybrid"):
        _create_hybrid_index(
            indexer_client, index_client, index_name,
            ai_services_endpoint, embedding_model,
            storage_resource_id, container, semantic_config=False,
        )
    elif arch_name in ("hybrid-reranker", "hybrid-llm-enriched"):
        _create_hybrid_index(
            indexer_client, index_client, index_name,
            ai_services_endpoint, embedding_model,
            storage_resource_id, container, semantic_config=True,
        )
    elif arch_name == "multi-vector":
        from retrieve.indexing.advanced import create_multivector_index
        create_multivector_index(
            endpoint=endpoint,
            index_name=index_name,
            ai_services_endpoint=ai_services_endpoint,
            embedding_model=embedding_model,
            storage_account=storage_account,
            resource_group=resource_group,
            container=container,
            cohere_uri=cohere_uri,
            cohere_model_name=cohere_model_name,
            cohere_key=cohere_key,
            custom_embedding_uri=custom_embedding_uri,
            custom_embedding_key=custom_embedding_key,
            custom_embedding_dimensions=custom_embedding_dimensions,
            custom_embedding_header_name=custom_embedding_header_name,
        )
    elif arch_name == "agentic-kb":
        # Agentic KB sits on top of a hybrid-reranker index.
        # First ensure the underlying index exists.
        base_index = f"{index_name}-base"
        _create_hybrid_index(
            indexer_client, index_client, base_index,
            ai_services_endpoint, embedding_model,
            storage_resource_id, container, semantic_config=True,
        )
        from retrieve.indexing.advanced import create_agentic_kb
        create_agentic_kb(
            endpoint=endpoint,
            index_name=base_index,
            ai_services_endpoint=ai_services_endpoint,
            kb_name=index_name,
            llm_model=llm_model,
        )
    elif arch_name == "graphrag":
        if not corpus_dir:
            console.print(
                "  [yellow]graphrag: corpus_dir required for GraphRAG indexing[/yellow]"
            )
            return
        from retrieve.indexing.advanced import run_graphrag_indexing
        return run_graphrag_indexing(
            corpus_dir=corpus_dir,
            storage_account=storage_account,
            ai_services_endpoint=ai_services_endpoint,
            search_endpoint=endpoint,
            cosmos_endpoint=cosmos_endpoint,
            function_endpoint=function_endpoint,
            graph_worker_endpoint=graph_worker_endpoint,
            embedding_model=embedding_model,
            llm_model=llm_model,
        )
    elif arch_name == "lightrag":
        if not corpus_dir:
            console.print(
                "  [yellow]lightrag: corpus_dir required for LightRAG indexing[/yellow]"
            )
            return
        from retrieve.indexing.advanced import run_lightrag_indexing
        return run_lightrag_indexing(
            corpus_dir=corpus_dir,
            ai_services_endpoint=ai_services_endpoint,
            container_app_endpoint=container_app_endpoint,
            embedding_model=embedding_model,
            llm_model=llm_model,
        )
    else:
        console.print(f"  [yellow]{arch_name}: index builder not yet implemented[/yellow]")


def _create_keyword_index(
    indexer_client: SearchIndexerClient,
    index_client: SearchIndexClient,
    index_name: str,
    storage_resource_id: str,
    container: str,
):
    """Keyword-only index per azure-ai-search.md skill."""
    console.print(f"  [cyan]keyword[/cyan]: creating index '{index_name}'...")

    # 1. Data source  ResourceId connection (managed identity, no keys)
    ds = SearchIndexerDataSourceConnection(
        name=f"{index_name}-ds",
        type="azureblob",
        connection_string=f"ResourceId={storage_resource_id};",
        container=SearchIndexerDataContainer(name=container),
    )
    indexer_client.create_or_update_data_source_connection(ds)

    # 2. Index  keyword fields only (per azure-ai-search.md Keyword-Only pattern)
    # Important: keep large body text searchable-only. Making content filterable,
    # facetable, or sortable can trigger the 32 KB Azure AI Search term limit.
    # If field-level schema toggles are added later, enforce this as a guardrail or
    # route long text through chunking/projection instead of enabling exact-term modes.
    index = SearchIndex(
        name=index_name,
        fields=[
            SimpleField(name="id", type=SearchFieldDataType.String, key=True, filterable=True),
            SearchableField(name="content", type=SearchFieldDataType.String),
            SearchableField(name="title", type=SearchFieldDataType.String, filterable=True),
            SearchableField(
                name="doc_id",
                type=SearchFieldDataType.String,
                filterable=True,
                sortable=True,
            ),
            SimpleField(
                name="metadata_storage_name",
                type=SearchFieldDataType.String,
                filterable=True,
            ),
            SimpleField(
                name="metadata_storage_path",
                type=SearchFieldDataType.String,
                filterable=True,
            ),
        ],
    )
    index_client.create_or_update_index(index)

    # 3. Indexer with markdown oneToMany parsing (per azure-indexer-pipeline.md)
    indexer = SearchIndexer(
        name=f"{index_name}-indexer",
        data_source_name=f"{index_name}-ds",
        target_index_name=index_name,
        parameters={
            "configuration": {
                "parsingMode": "markdown",
                "markdownParsingSubmode": "oneToMany",
                "dataToExtract": "contentAndMetadata",
            },
        },
        field_mappings=[
            # doc_id = filename without extension — generalizable document identifier
            {"sourceFieldName": "metadata_storage_name", "targetFieldName": "doc_id",
             "mappingFunction": {"name": "extractTokenAtPosition",
                                 "parameters": {"delimiter": ".", "position": 0}}},
        ],
    )
    indexer_client.create_or_update_indexer(indexer)
    try:
        indexer_client.run_indexer(f"{index_name}-indexer")
    except Exception as e:
        if "concurrent" in str(e).lower() or "in progress" in str(e).lower():
            pass  # Already running due to create_or_update
        else:
            raise
    console.print("  [green]keyword[/green] index + indexer created and running")
    emit_progress(
        f"Keyword index '{index_name}' created and running",
        stage="search_index.create", architecture="keyword", index_name=index_name,
    )


def _create_hybrid_index(
    indexer_client: SearchIndexerClient,
    index_client: SearchIndexClient,
    index_name: str,
    ai_services_endpoint: str,
    embedding_model: str,
    storage_resource_id: str,
    container: str,
    semantic_config: bool = False,
):
    """Hybrid index per azure-ai-foundry.md Step 3-5 walkthrough + azure-ai-search.md patterns."""
    label = "hybrid-reranker" if semantic_config else "hybrid"
    console.print(f"  [cyan]{label}[/cyan]: creating index '{index_name}'...")

    dims = 3072 if "large" in embedding_model else 1536

    # 1. Data source
    ds = SearchIndexerDataSourceConnection(
        name=f"{index_name}-ds",
        type="azureblob",
        connection_string=f"ResourceId={storage_resource_id};",
        container=SearchIndexerDataContainer(name=container),
    )
    indexer_client.create_or_update_data_source_connection(ds)

    # 2. Index — projections require parent_id and keyword analyzer on the key field.
    # Same guardrail applies here: large text fields should stay searchable-only unless
    # they are pre-chunked into smaller units that won't exceed the 32 KB term limit.
    fields = [
        SearchField(name="id", type=SearchFieldDataType.String, key=True, filterable=True,
                    analyzer_name="keyword"),
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
        SearchField(name="metadata_storage_name", type=SearchFieldDataType.String,
                    filterable=True),
        SearchField(
            name="content_vector",
            type=SearchFieldDataType.Collection(SearchFieldDataType.Single),
            searchable=True,
            vector_search_dimensions=dims,
            vector_search_profile_name="vector-profile",
        ),
    ]

    # Vector search config per azure-ai-foundry.md Step 3
    vector_search = VectorSearch(
        algorithms=[
            HnswAlgorithmConfiguration(
                name="hnsw-config",
                parameters=HnswParameters(
                    m=8,               # default 4; higher m → better recall at slight memory cost
                    ef_construction=800,  # default 400; better index quality at build time
                    ef_search=500,     # default 500; controls recall vs speed at query time
                    metric="cosine",
                ),
            )
        ],
        profiles=[
            VectorSearchProfile(
                name="vector-profile",
                algorithm_configuration_name="hnsw-config",
                vectorizer_name="openai-vectorizer",
            )
        ],
        vectorizers=[
            AzureOpenAIVectorizer(
                vectorizer_name="openai-vectorizer",
                parameters=AzureOpenAIVectorizerParameters(
                    resource_url=ai_services_endpoint,
                    deployment_name=embedding_model,
                    model_name=embedding_model,
                ),
            )
        ],
    )

    index = SearchIndex(name=index_name, fields=fields, vector_search=vector_search)

    # Add semantic config if needed (per azure-ai-search.md Hybrid Index pattern)
    if semantic_config:
        index.semantic_search = SemanticSearch(
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

    index_client.create_or_update_index(index)

    # 3. Skillset — use the documented SplitSkill + projection pattern.
    skillset = SearchIndexerSkillset(
        name=f"{index_name}-skillset",
        skills=[
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
        ],
        index_projection=SearchIndexerIndexProjection(
            selectors=[
                SearchIndexerIndexProjectionSelector(
                    target_index_name=index_name,
                    parent_key_field_name="parent_id",
                    source_context="/document/chunks/*",
                    mappings=[
                        InputFieldMappingEntry(name="content", source="/document/chunks/*"),
                        InputFieldMappingEntry(
                            name="content_vector",
                            source="/document/chunks/*/content_vector",
                        ),
                        InputFieldMappingEntry(
                            name="title",
                            source="/document/metadata_storage_name",
                        ),
                        InputFieldMappingEntry(
                            name="metadata_storage_name",
                            source="/document/metadata_storage_name",
                        ),
                        InputFieldMappingEntry(
                            name="doc_id",
                            source="/document/metadata_storage_name",
                        ),
                    ],
                )
            ],
            parameters=SearchIndexerIndexProjectionsParameters(
                projection_mode="skipIndexingParentDocuments",
            ),
        ),
    )
    indexer_client.create_or_update_skillset(skillset)

    # 4. Indexer — projections handle chunk fan-out and vector field mapping.
    indexer = SearchIndexer(
        name=f"{index_name}-indexer",
        data_source_name=f"{index_name}-ds",
        target_index_name=index_name,
        skillset_name=f"{index_name}-skillset",
        parameters={
            "batchSize": 1,
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
            pass  # Already running due to create_or_update
        else:
            raise
    console.print(f"  [green]{label}[/green] index + skillset + indexer created and running")
    emit_progress(
        f"{label} index '{index_name}' created and running",
        stage="search_index.create", architecture=label, index_name=index_name,
    )


def wait_for_indexer(endpoint: str, indexer_name: str, timeout: int = 1800) -> dict:
    """Poll indexer status until complete or timeout.

    Returns dict with 'status', 'item_count', 'failed_count', 'errors' keys.
    'errors' contains up to 3 sample error dicts with 'key' and 'message' fields.
    """
    credential = DefaultAzureCredential()

    console.print(f"  Waiting for indexer '{indexer_name}'...")
    start = time.time()
    while time.time() - start < timeout:
        try:
            status = _search_rest_get(
                endpoint,
                f"indexers('{quote(indexer_name, safe='')}')/status",
                credential,
            )
            last = status.get("lastResult") or {}
            last_status = str(last.get("status", ""))
            if last and last_status in ("success", "transientFailure"):
                failed = int(last.get("failedItemCount") or last.get("itemsFailed") or 0)
                count = int(last.get("itemCount") or last.get("itemsProcessed") or 0)
                console.print(
                    f"  Indexer '{indexer_name}': {last_status} - "
                    f"{count} docs, {failed} failed"
                )
                # With oneToMany parsing, item_count reflects the number of
                # sub-documents (heading sections), not source blobs.
                # Zero count with zero failures may indicate RBAC propagation delay.
                if count == 0 and failed == 0:
                    try:
                        index_name = indexer_name.replace("-indexer", "")
                        stats = _search_rest_get(
                            endpoint,
                            f"indexes('{quote(index_name, safe='')}')/stats",
                            credential,
                        )
                        doc_count = int(
                            stats.get("documentCount")
                            or stats.get("document_count")
                            or 0
                        )
                        console.print(
                            f"  (oneToMany parsed — {doc_count} docs in index)"
                        )
                    except Exception:
                        pass  # stats check is informational only

                # Surface sample errors so failures are diagnosable
                sample_errors: list[dict] = []
                errors = last.get("errors") or []
                if errors:
                    for err in errors[:3]:
                        sample_errors.append({
                            "key": err.get("key", ""),
                            "message": err.get("errorMessage") or err.get("message") or "",
                        })
                    console.print(f"  [red]Sample errors (first {len(sample_errors)}):[/red]")
                    for e in sample_errors:
                        console.print(f"    [{e['key']}] {e['message']}")

                return {
                    "status": last_status,
                    "item_count": count,
                    "failed_count": failed,
                    "errors": sample_errors,
                }
        except Exception as e:
            log.debug("Indexer status check failed: %s", e)
        time.sleep(10)
    console.print(f"  [yellow]Indexer '{indexer_name}' did not complete within {timeout}s[/yellow]")
    return {"status": "timeout", "item_count": 0, "failed_count": 0, "errors": []}


def rerun_indexer(endpoint: str, indexer_name: str):
    """Reset and re-run an indexer."""
    credential = DefaultAzureCredential()
    indexer_client = SearchIndexerClient(endpoint, credential)
    indexer_client.reset_indexer(indexer_name)
    indexer_client.run_indexer(indexer_name)
    console.print(f"  Indexer '{indexer_name}' reset and re-running")
