# Skill: Azure AI Search — Indexers, Skillsets & Integrated Vectorization

> For: Retrieve solution accelerator — configuring indexer pipelines that ingest documents from blob storage, chunk them, embed them, and populate search indexes.

## IMPORTANT: When This Pipeline is NOT Needed

If using the **Knowledge Bases (agentic-kb) architecture**, the Knowledge Source auto-ingest handles the entire pipeline — data source, indexer, skillset, and index are all managed by the KB. You only need this manual pipeline for non-KB architectures (keyword, single-vector, hybrid, hybrid-reranker, multi-vector). See `azure-ai-search-agentic.md`.

## When to Use
- Setting up blob indexers with Markdown parsing (non-KB architectures)
- Configuring skillsets for chunking (SplitSkill) + embedding (AzureOpenAIEmbeddingSkill)
- Integrated vectorization (end-to-end: blob → chunk → embed → index)
- Configuring different chunking strategies for SOTA eval mode
- **ChatCompletionSkill for LLM enrichment at index time** (cross-reference extraction, summary generation, topic classification)

## Indexer Pipeline Flow
```
Blob Storage (Markdown files)
  → Data Source (managed identity connection)
    → Indexer (parsingMode: markdown)
      → Skillset (chunk → embed)
        → Index (text + vector fields)
```

## PREREQUISITE: Embedding Model Deployment Decision Tree

Before building any index with vector fields, you must deploy an embedding model. The deployment method and AI Search wiring depend on which model you chose.

### Decision Flow
```
Architecture needs vector search?
  ├─ NO (keyword-only) → skip this section entirely
  └─ YES → which embedding model?
       │
       ├─ Azure OpenAI model (text-embedding-3-small / 3-large) ← RECOMMENDED DEFAULT
       │    1. Deploy Foundry resource + model deployment (see azure-ai-foundry.md)
       │    2. Grant Search managed identity "Cognitive Services OpenAI User" role on Foundry resource
       │    3. Index-time: use AzureOpenAIEmbeddingSkill (resourceUri + deploymentId + modelName)
       │    4. Query-time: use AzureOpenAIVectorizer (same resourceUri + deploymentId + modelName)
       │    ⚠️ Foundry resource MUST exist before index creation — vectorizer references the endpoint
       │
       ├─ Foundry Catalog model (Cohere embed-v3/v4, etc.)
       │    1. Deploy model via Foundry Model Catalog → serverless API endpoint (pay-per-token)
       │    2. Index-time: use AMLSkill pointing at the inference endpoint
       │    3. Query-time: use AMLVectorizer pointing at the same endpoint
       │    See embedding-models.md for catalog model names
       │
       └─ Open-weight model (BGE-M3, etc.) via Foundry managed compute
            1. Deploy model to Foundry managed compute endpoint (dedicated VMs, managed by Foundry)
            2. Index-time: use AMLSkill with `resourceId` (managed identity auth)
            3. Query-time: use AMLVectorizer with same `resourceId`
            ⚠️ No self-hosting (no ACI, no AKS, no Container Apps) — Foundry manages the compute
            See azure-ai-foundry.md for managed compute deployment
```

### Critical Rules
- **Skill and vectorizer MUST use the same model** — if you embed documents with `text-embedding-3-large` at index time, you must vectorize queries with `text-embedding-3-large` at query time. Mismatched models = garbage results.
- **Dimensions must match everywhere** — the embedding skill output dimensions, the vector field dimensions in the index schema, and the vectorizer dimensions must all be identical.
- **Foundry before Search** — if using Azure OpenAI or Catalog models, the Foundry account and model deployment must exist before you create the index (the vectorizer config references the endpoint). See `azure-ai-foundry.md` CRITICAL section.
- **Role assignment propagation** — after creating the `Cognitive Services OpenAI User` role assignment, wait ~30-60 seconds before the indexer can call the embedding endpoint. Bicep `dependsOn` won't help — it's Azure AD propagation.

## Data Source Configuration

### Blob Storage with Managed Identity (recommended)
```python
from azure.search.documents.indexes.models import (
    SearchIndexerDataSourceConnection,
    SearchIndexerDataContainer
)

data_source = SearchIndexerDataSourceConnection(
    name="policies-blob",
    type="azureblob",
    connection_string=f"ResourceId=/subscriptions/{sub}/resourceGroups/{rg}/providers/Microsoft.Storage/storageAccounts/{account};",
    container=SearchIndexerDataContainer(name="policies")
)
indexer_client.create_or_update_data_source_connection(data_source)
```

### Supported Data Source Types
| Type | Connection |
|---|---|
| `azureblob` | Blob Storage |
| `cosmosdb` | Cosmos DB (SQL, MongoDB, Gremlin) |
| `azuresql` | Azure SQL |
| `adlsgen2` | Data Lake Gen2 |
| `sharepoint` | SharePoint Online |
| `onelake` | Fabric OneLake |

## Markdown Parsing Modes

### oneToMany (default for markdown)
Splits Markdown files by headers into multiple search documents. Each heading section becomes a separate document.

### oneToOne
Entire Markdown file becomes one search document. Header structure is preserved as metadata.

### Markdown Header Depth
Controls heading split depth: `h1` through `h6` (default `h6`).

```json
{
  "parameters": {
    "configuration": {
      "parsingMode": "markdown",
      "markdownParsingSubmode": "oneToMany",
      "markdownHeaderDepth": "h3"
    }
  }
}
```

## Skillset Components

### SplitSkill (Text Chunking)
```python
from azure.search.documents.indexes.models import (
    SplitSkill, InputFieldMappingEntry, OutputFieldMappingEntry
)

split_skill = SplitSkill(
    name="chunk-skill",
    text_split_mode="pages",
    maximum_page_length=2000,
    page_overlap_length=500,
    inputs=[InputFieldMappingEntry(name="text", source="/document/content")],
    outputs=[OutputFieldMappingEntry(name="textItems", target_name="chunks")]
)
```

#### Chunking Parameters
| Parameter | Options | Notes |
|---|---|---|
| `textSplitMode` | `pages` / `sentences` | `pages` for fixed-size chunks |
| `maximumPageLength` | Integer | Max chars or tokens per chunk |
| `pageOverlapLength` | Integer | Overlap between chunks |
| `unit` | `characters` / `azureOpenAITokens` | Token-based chunking aligns with model limits |
| `azureOpenAITokenizerParameters.encoderModelName` | `cl100k_base` / `r50k_base` / `p50k_base` | Tokenizer for token-based chunking |

### AzureOpenAIEmbeddingSkill
```python
from azure.search.documents.indexes.models import AzureOpenAIEmbeddingSkill

embedding_skill = AzureOpenAIEmbeddingSkill(
    name="embed-skill",
    resource_url="https://{resource}.openai.azure.com",
    deployment_name="text-embedding-3-small",
    model_name="text-embedding-3-small",
    dimensions=1536,
    inputs=[InputFieldMappingEntry(name="text", source="/document/chunks/*")],
    outputs=[OutputFieldMappingEntry(name="embedding", target_name="vector")]
)
```

### ChatCompletionSkill (LLM enrichment at index time — built-in, no Functions needed)

This is one of the most powerful and underused skills. It calls Azure OpenAI Chat Completions for **every document** during indexing. Despite the `#Microsoft.Skills.Custom.` prefix, it's a first-party built-in skill.

#### Use Cases for Retrieve

| Use Case | Input | Output | Impact on Retrieval |
|---|---|---|---|
| **Cross-reference extraction** | Document content | `referenced_policies: ["100-8", "205-3"]` | Filterable field enables cross-policy retrieval WITHOUT GraphRAG |
| **Per-chunk summary** | Chunk content | `summary: "Rules for disclosing client info..."` | Better semantic search, captions |
| **Topic/category classification** | Chunk content | `topics: ["confidentiality", "disclosure", "subpoenas"]` | Facetable field for filtering, better keyword matches |
| **Keyword generation** | Chunk content | `search_keywords: ["HIPAA", "privacy", "PHI"]` | Improves keyword retrieval for jargon-heavy policy content |

This is a **potential SOTA toggle**: "LLM enrichment on/off" — adds cost at index time ($0.01-0.03 per chunk) but can significantly improve retrieval quality without requiring GraphRAG.

#### Example: Cross-Reference Extraction Skill
```json
{
  "@odata.type": "#Microsoft.Skills.Custom.ChatCompletionSkill",
  "name": "extract-cross-refs",
  "uri": "https://{resource}.openai.azure.com/openai/deployments/gpt-41/chat/completions",
  "apiKey": null,
  "authResourceId": "https://cognitiveservices.azure.com",
  "commonModelParameters": {
    "model": "gpt-4.1",
    "temperature": 0.0,
    "maxTokens": 300
  },
  "responseFormat": { "type": "jsonObject" },
  "inputs": [
    { "name": "user", "source": "/document/content" }
  ],
  "outputs": [
    { "name": "response", "targetName": "llm_enrichment" }
  ],
  "context": "/document",
  "batchSize": 1,
  "degreeOfParallelism": 5
}
```

System message (set via `inputs` with role `system`):
```
Extract all policy cross-references from this text. Return JSON: 
{"referenced_policies": ["100-8", "205-3"], "topics": ["confidentiality", "disclosure"], "summary": "one-sentence summary"}
```

#### Example: Using Output in Index Schema
```python
# Add enriched fields to the index
SearchField(name="referenced_policies", type="Collection(Edm.String)", filterable=True, facetable=True),
SearchField(name="topics", type="Collection(Edm.String)", filterable=True, facetable=True),
SearchField(name="summary", type="Edm.String", searchable=True),
```

These fields enable:
- `$filter=referenced_policies/any(p: p eq '100-8')` — find all docs that reference policy 100-8
- `facet=topics` — see what topics appear in search results
- Searching against `summary` field in addition to full content

### DocumentIntelligenceLayoutSkill
For PDF/image extraction with structure preservation:
```json
{
  "@odata.type": "#Microsoft.Skills.Util.DocumentIntelligenceLayoutSkill",
  "outputFormat": "markdown",
  "outputMode": "oneToMany",
  "markdownHeaderDepth": "h6",
  "chunkingProperties": {
    "unit": "characters",
    "maximumLength": 500,
    "overlapLength": 50
  }
}
```

## Full Skillset Example
```python
from azure.search.documents.indexes.models import SearchIndexerSkillset

skillset = SearchIndexerSkillset(
    name="policy-skillset",
    skills=[split_skill, embedding_skill],
    # No cognitive_services_account needed — managed identity auth is automatic
    # when Search has "Cognitive Services OpenAI User" role on the Foundry resource
)
indexer_client.create_or_update_skillset(skillset)
```

## Indexer Configuration
```python
from azure.search.documents.indexes.models import (
    SearchIndexer, IndexingParameters, IndexingParametersConfiguration,
    FieldMapping
)

indexer = SearchIndexer(
    name="policy-indexer",
    data_source_name="policies-blob",
    target_index_name="policies-index",
    skillset_name="policy-skillset",
    parameters=IndexingParameters(
        configuration=IndexingParametersConfiguration(
            parsing_mode="markdown",
            markdown_parsing_submode="oneToMany",
            markdown_header_depth="h3"
        )
    ),
    field_mappings=[
        FieldMapping(source_field_name="metadata_storage_name", target_field_name="source_file")
    ]
)
indexer_client.create_or_update_indexer(indexer)
```

### Run & Monitor Indexer
```python
indexer_client.run_indexer("policy-indexer")

# Check status
status = indexer_client.get_indexer_status("policy-indexer")
print(status.last_result.status)  # "success" | "transientFailure" | "inProgress"
print(status.last_result.items_processed)
print(status.last_result.items_failed)
```

## Index Projections — REQUIRED for SplitSkill + Embedding Pipelines

> **CRITICAL:** When using SplitSkill to produce multiple chunks per document, you MUST use
> index projections to map each chunk to a separate index document. Do NOT use
> `output_field_mappings` on the indexer for chunked/embedded data — it causes
> `Collection(Edm.Double)` vs `Collection(Edm.Single)` type mismatches and broken
> array-to-scalar mapping.

### When to Use Index Projections
- **Always** when SplitSkill produces `/document/chunks/*` and an embedding skill produces `/document/chunks/*/content_vector`
- The projections tell the indexer how to "fan out" each chunk into its own search document
- Without projections, the indexer tries to stuff an array of chunks into a single scalar field → 100% failure rate

### When NOT to Use (use output_field_mappings instead)
- Simple 1:1 document mapping (no SplitSkill, no chunking)
- Keyword-only indexes where Markdown `oneToMany` parsing already splits by heading

### Index Schema Requirements for Projections
When using index projections, the target index MUST have:
1. **`analyzer_name="keyword"` on the key field** — projections generate composite keys (parent_id + chunk_index); the keyword analyzer prevents tokenization of these keys
2. **`parent_id` field** (`Edm.String`, filterable) — projections auto-populate this with the parent document key

```python
fields = [
    SearchField(name="id", type=SearchFieldDataType.String, key=True, filterable=True,
                analyzer_name="keyword"),   # ← REQUIRED for projections
    SearchField(name="parent_id", type=SearchFieldDataType.String, filterable=True),  # ← REQUIRED
    SearchField(name="content", type=SearchFieldDataType.String, searchable=True),
    SearchField(name="title", type=SearchFieldDataType.String, searchable=True, filterable=True),
    SearchField(
        name="content_vector",
        type=SearchFieldDataType.Collection(SearchFieldDataType.Single),
        searchable=True,
        vector_search_dimensions=3072,
        vector_search_profile_name="vector-profile",
    ),
]
```

### Adding Projections to the Skillset
```python
from azure.search.documents.indexes.models import (
    SearchIndexerIndexProjection,
    SearchIndexerIndexProjectionSelector,
    SearchIndexerIndexProjectionsParameters,
    InputFieldMappingEntry,
)

skillset = SearchIndexerSkillset(
    name="policy-skillset",
    skills=[split_skill, embedding_skill],
    index_projection=SearchIndexerIndexProjection(           # ← singular, NOT index_projections
        selectors=[
            SearchIndexerIndexProjectionSelector(
                target_index_name="policies-index",          # ← index MUST already exist
                parent_key_field_name="parent_id",
                source_context="/document/chunks/*",
                mappings=[
                    InputFieldMappingEntry(name="content", source="/document/chunks/*"),
                    InputFieldMappingEntry(name="content_vector", source="/document/chunks/*/content_vector"),
                    InputFieldMappingEntry(name="title", source="/document/metadata_storage_name"),
                ],
            )
        ],
        parameters=SearchIndexerIndexProjectionsParameters(
            projection_mode="skipIndexingParentDocuments",    # ← only index chunks, not parent blobs
        ),
    ),
)
```

### SDK Attribute Name
The Python SDK attribute is **`index_projection`** (singular) on `SearchIndexerSkillset`. Using `index_projections` (plural) silently does nothing — the projections won't be applied and all documents will fail.

### Projection Modes
| Mode | Behavior |
|---|---|
| `skipIndexingParentDocuments` | Only chunk documents are indexed (recommended) |
| `includeIndexingParentDocuments` | Both parent blob doc AND chunk docs are indexed |

### Indexer Configuration with Projections
When using index projections, the indexer should **NOT** have `field_mappings` or `output_field_mappings` — the projections handle all field mapping:
```python
indexer = SearchIndexer(
    name="policy-indexer",
    data_source_name="policies-blob",
    target_index_name="policies-index",
    skillset_name="policy-skillset",
    parameters={
        "configuration": {
            "parsingMode": "markdown",
            "markdownParsingSubmode": "oneToMany",
            "dataToExtract": "contentAndMetadata",
        },
    },
    # NO field_mappings — projections handle key generation
    # NO output_field_mappings — projections handle chunk→document mapping
)
```

### Creation Order (CRITICAL)
```
1. Data source          (no dependencies)
2. Index                (must exist BEFORE skillset — projections reference it by name)
3. Skillset             (references the index in projection selectors)
4. Indexer              (references all three above)
```
If you create the skillset before the index, the projection selector validation will fail because the target index doesn't exist yet.

## Dependencies
- **Creation order**: data source → index → skillset → indexer (when using projections)
- Blob Storage must have data uploaded BEFORE indexer runs
- OpenAI resource + deployment must exist BEFORE skillset is created
- `Storage Blob Data Reader` role assigned to Search's managed identity
- `Cognitive Services OpenAI User` role assigned to Search's managed identity
- Role propagation can take up to 10 minutes after assignment
