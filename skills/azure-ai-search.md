# Skill: Azure AI Search — Index & Query Management

> For: Retrieve solution accelerator — creating, configuring, and querying search indexes across multiple retrieval architectures.

## When to Use
- Creating search indexes with different configurations (keyword-only, vector, hybrid, semantic)
- Configuring vector search profiles, vectorizers, compression
- Running search queries and collecting retrieval metrics
- Managing indexers, data sources, skillsets

## API Version
`2025-11-01-preview` (latest preview with Knowledge Bases / agentic retrieval)
Stable: `2024-07-01`

## Python SDK
```
pip install azure-search-documents azure-identity
```

### Key Classes
| Class | Import | Purpose |
|---|---|---|
| `SearchClient` | `azure.search.documents` | Query documents, upload/merge/delete docs |
| `SearchIndexClient` | `azure.search.documents.indexes` | Create/update/delete indexes, aliases, synonym maps |
| `SearchIndexerClient` | `azure.search.documents.indexes` | Manage indexers, data sources, skillsets |

### Client Initialization (managed identity)
```python
from azure.identity import DefaultAzureCredential
from azure.search.documents import SearchClient
from azure.search.documents.indexes import SearchIndexClient, SearchIndexerClient

credential = DefaultAzureCredential()
endpoint = "https://{service-name}.search.windows.net"

index_client = SearchIndexClient(endpoint, credential)
indexer_client = SearchIndexerClient(endpoint, credential)
search_client = SearchClient(endpoint, index_name="my-index", credential=credential)
```

## Index Configuration Patterns

### Keyword-Only Index
```python
from azure.search.documents.indexes.models import (
    SearchIndex, SearchField, SearchFieldDataType
)

index = SearchIndex(
    name="keyword-index",
    fields=[
        SearchField(name="id", type=SearchFieldDataType.String, key=True),
        SearchField(name="content", type=SearchFieldDataType.String, searchable=True),
        SearchField(name="title", type=SearchFieldDataType.String, searchable=True, filterable=True),
        SearchField(name="policy_id", type=SearchFieldDataType.String, filterable=True, facetable=True),
    ]
)
```

### Vector Index (single vector field)
```python
from azure.search.documents.indexes.models import (
    SearchIndex, SearchField, SearchFieldDataType,
    VectorSearch, HnswAlgorithmConfiguration, VectorSearchProfile,
    AzureOpenAIVectorizer, AzureOpenAIVectorizerParameters
)

index = SearchIndex(
    name="vector-index",
    fields=[
        SearchField(name="id", type=SearchFieldDataType.String, key=True),
        SearchField(name="content", type=SearchFieldDataType.String, searchable=True),
        SearchField(name="content_vector", type="Collection(Edm.Single)",
                    searchable=True, vector_search_dimensions=1536,
                    vector_search_profile_name="my-profile"),
    ],
    vector_search=VectorSearch(
        algorithms=[HnswAlgorithmConfiguration(name="my-hnsw")],
        profiles=[VectorSearchProfile(
            name="my-profile",
            algorithm_configuration_name="my-hnsw",
            vectorizer_name="my-openai-vectorizer"
        )],
        vectorizers=[AzureOpenAIVectorizer(
            vectorizer_name="my-openai-vectorizer",
            parameters=AzureOpenAIVectorizerParameters(
                resource_url="https://{openai-resource}.openai.azure.com",
                deployment_name="text-embedding-3-small",
                model_name="text-embedding-3-small"
            )
        )]
    )
)
```

> **If using with SplitSkill + AzureOpenAIEmbeddingSkill (indexer pipeline):** The index
> above needs two additional fields: `parent_id` (Edm.String, filterable) and
> `analyzer_name="keyword"` on the id key field. These are required by index projections.
> See `azure-indexer-pipeline.md` for the complete projection pattern.

### Hybrid Index (keyword + vector + semantic reranker)
Add `SemanticSearch` configuration to any vector index:
```python
from azure.search.documents.indexes.models import (
    SemanticConfiguration, SemanticPrioritizedFields,
    SemanticField, SemanticSearch
)

semantic_config = SemanticConfiguration(
    name="my-semantic-config",
    prioritized_fields=SemanticPrioritizedFields(
        title_field=SemanticField(field_name="title"),
        content_fields=[SemanticField(field_name="content")],
        keywords_fields=[SemanticField(field_name="policy_id")]
    )
)

# Add to index:
index.semantic_search = SemanticSearch(configurations=[semantic_config])
```

### Vector Compression (scalar quantization)
```python
from azure.search.documents.indexes.models import (
    ScalarQuantizationCompression, ScalarQuantizationParameters
)

vector_search.compressions = [
    ScalarQuantizationCompression(
        compression_name="my-sq",
        rerank_with_original_vectors=True,
        default_oversampling=10,
        parameters=ScalarQuantizationParameters(quantized_data_type="int8")
    )
]
# Reference in profile: compression_name="my-sq"
```

## Querying

### Keyword Search
```python
results = search_client.search(search_text="SNAP eligibility", top=10)
```

### Vector Search
```python
from azure.search.documents.models import VectorizableTextQuery

results = search_client.search(
    search_text=None,
    vector_queries=[VectorizableTextQuery(
        text="SNAP eligibility",
        k_nearest_neighbors=50,
        fields="content_vector"
    )],
    top=10
)
```

### Hybrid Search (keyword + vector + semantic reranker)
```python
results = search_client.search(
    search_text="SNAP eligibility",
    vector_queries=[VectorizableTextQuery(
        text="SNAP eligibility",
        k_nearest_neighbors=50,
        fields="content_vector"
    )],
    query_type="semantic",
    semantic_configuration_name="my-semantic-config",
    query_caption="extractive",
    query_answer="extractive",
    top=10
)
```

### Collecting Metrics from Results
```python
for result in results:
    doc_id = result["id"]
    score = result["@search.score"]                # RRF or BM25 score
    reranker_score = result.get("@search.reranker_score")  # semantic score
    captions = result.get("@search.captions", [])
```

## Vector Search Algorithms
| Algorithm | Config Class | When to Use |
|---|---|---|
| HNSW | `HnswAlgorithmConfiguration` | Default. Approximate NN, fast, tunable. |
| Exhaustive KNN | `ExhaustiveKnnAlgorithmConfiguration` | Exact NN, slower, use for small indexes or baselines. |

### HNSW Parameters
- `m`: 4-10 (default 4) — bidirectional links per node
- `efConstruction`: 100-1000 (default 400) — index build quality
- `efSearch`: 100-1000 (default 500) — query search quality
- `metric`: `cosine` | `euclidean` | `dotProduct` | `hamming`

## Vector Field Data Types
| Type | Use |
|---|---|
| `Collection(Edm.Single)` | Float32 vectors (standard) |
| `Collection(Edm.Half)` | Float16 vectors (50% storage savings) |
| `Collection(Edm.SByte)` | Int8 scalar-quantized |
| `Collection(Edm.Byte)` | Binary quantized |

## REST API Paths
| Operation | Method | Path |
|---|---|---|
| Create index | POST | `/indexes` |
| Create/update index | PUT | `/indexes('{name}')` |
| Delete index | DELETE | `/indexes('{name}')` |
| Search documents | POST | `/indexes('{name}')/docs/search.post.search` |
| Count documents | GET | `/indexes('{name}')/docs/$count` |
| Index statistics | GET | `/indexes('{name}')/search.stats` |
| Create data source | POST | `/datasources` |
| Create indexer | POST | `/indexers` |
| Run indexer | POST | `/indexers('{name}')/search.run` |
| Indexer status | GET | `/indexers('{name}')/search.status` |
| Create skillset | POST | `/skillsets` |

## Bicep Resource
```bicep
resource searchService 'Microsoft.Search/searchServices@2023-11-01' = {
  name: searchName
  location: location
  sku: { name: 'basic' }  // basic | standard | standard2
  identity: { type: 'SystemAssigned' }
  properties: {
    replicaCount: 1
    partitionCount: 1
    hostingMode: 'default'
  }
}
```

## Required RBAC Roles
| Connection | Role | GUID |
|---|---|---|
| Search → Blob Storage | Storage Blob Data Reader | `2a2b9908-6ea1-4ae2-8e65-a410df84e7d1` |
| Search → Azure OpenAI | Cognitive Services OpenAI User | `5e0bd9bd-7b93-4f28-af87-19fc36ad61bd` |
| Deployer → Search (manage) | Search Service Contributor | `7ca78c08-252a-4471-8644-bb5ff32d4ba0` |
| Deployer → Search (query) | Search Index Data Reader | `1407120a-92aa-4202-b7e9-c0e197c71c8f` |

## Python SDK Pitfalls

| Pitfall | Symptom | Fix |
|---|---|---|
| `retrievable=True` on `SearchField` | UserWarning at runtime, parameter silently ignored | Don't pass it — fields are retrievable by default. Use `hidden=True` to make non-retrievable. |
| `index_projections` (plural) on skillset | Projections silently not applied, 100% indexer failure | Use `index_projection` (singular) — the SDK attribute name |
| `output_field_mappings` for chunked vector data | `Collection(Edm.Double)` vs `Collection(Edm.Single)` type error, 100% failure | Use index projections on the skillset instead. See `azure-indexer-pipeline.md`. |
| Creating skillset before index (with projections) | Skillset creation fails — projection references non-existent index | Create index FIRST, then skillset. Order: data source → index → skillset → indexer. |
| Missing `analyzer_name="keyword"` on key field | Indexer fails when projections generate composite keys | Add `analyzer_name="keyword"` to the key field when using projections. |
| Missing `parent_id` field in index | Projection fails — no field to store parent document key | Add `SearchField(name="parent_id", type=SearchFieldDataType.String, filterable=True)`. |
| Missing `context` on `AzureOpenAIEmbeddingSkill` | Skill receives entire chunk array instead of iterating — all docs fail | Set `context="/document/chunks/*"` so the skill runs per-chunk. |
