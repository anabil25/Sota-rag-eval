# Azure AI Search API — Quick Reference

> API version `2025-11-01-preview` · 38 endpoints · 421 types
> For full property details → `search-api-overview.md`
> For type schemas/enums → `search-api-map.json`
> For raw swagger → `search.json`

---

## All 38 API Paths

### Indexes (6 paths)
| Path | Methods | Purpose |
|------|---------|---------|
| `/indexes` | GET, POST | List / create index |
| `/indexes?_overload=listWithSelectedProperties` | GET | List indexes with `$select` |
| `/indexes('{indexName}')` | GET, PUT, DELETE | CRUD single index |
| `/indexes('{indexName}')/search.stats` | GET | Doc count, storage size, vector index size |
| `/indexes('{indexName}')/search.analyze` | POST | Test analyzer tokenization |
| `/indexstats` | GET | Summary stats all indexes |

### Documents (9 paths)
| Path | Methods | Purpose |
|------|---------|---------|
| `/indexes('{indexName}')/docs` | GET | Search (query string) |
| `/indexes('{indexName}')/docs/search.post.search` | POST | Search (JSON body) |
| `/indexes('{indexName}')/docs/$count` | GET | Document count |
| `/indexes('{indexName}')/docs('{key}')` | GET | Lookup by key |
| `/indexes('{indexName}')/docs/search.suggest` | GET | Suggest (GET) |
| `/indexes('{indexName}')/docs/search.post.suggest` | POST | Suggest (POST) |
| `/indexes('{indexName}')/docs/search.autocomplete` | GET | Autocomplete (GET) |
| `/indexes('{indexName}')/docs/search.post.autocomplete` | POST | Autocomplete (POST) |
| `/indexes('{indexName}')/docs/search.index` | POST | Batch upload/merge/delete docs |

### Indexer Pipeline (14 paths)
| Path | Methods | Purpose |
|------|---------|---------|
| `/datasources` | GET, POST | List / create data sources |
| `/datasources('{name}')` | GET, PUT, DELETE | CRUD single data source |
| `/indexers` | GET, POST | List / create indexers |
| `/indexers('{name}')` | GET, PUT, DELETE | CRUD single indexer |
| `/indexers('{name}')/search.run` | POST | Run on demand |
| `/indexers('{name}')/search.status` | GET | Status & execution history |
| `/indexers('{name}')/search.reset` | POST | Reset change tracking |
| `/indexers('{name}')/search.resetdocs` | POST | Reset specific docs |
| `/indexers('{name}')/search.resync` | POST | Resync permissions |
| `/skillsets` | GET, POST | List / create skillsets |
| `/skillsets('{name}')` | GET, PUT, DELETE | CRUD single skillset |
| `/skillsets('{name}')/search.resetskills` | POST | Reset specific skills |
| `/synonymmaps` | GET, POST | List / create synonym maps |
| `/synonymmaps('{name}')` | GET, PUT, DELETE | CRUD single synonym map |

### Knowledge Bases (5 paths)
| Path | Methods | Purpose |
|------|---------|---------|
| `/knowledgebases` | GET, POST | List / create KBs |
| `/knowledgebases('{name}')` | GET, PUT, DELETE | CRUD single KB |
| `/knowledgebases('{name}')/retrieve` | POST | Agentic retrieval (multi-hop) |
| `/knowledgesources` | GET, POST | List / create sources |
| `/knowledgesources('{name}')` | GET, PUT, DELETE | CRUD single source |

### Other (4 paths)
| Path | Methods | Purpose |
|------|---------|---------|
| `/knowledgesources('{name}')/status` | GET | Source sync status |
| `/aliases` | GET, POST | List / create aliases |
| `/aliases('{name}')` | GET, PUT, DELETE | CRUD single alias |
| `/servicestats` | GET | Service counters & limits |

---

## Core Concepts at a Glance

### Index = schema + config
- **Fields**: name, type, key, searchable, filterable, sortable, facetable, retrievable
- **Vector search**: algorithm (HNSW or ExhaustiveKNN) + profile + vectorizer + optional compression
- **Semantic search**: SemanticConfiguration → prioritized title/content/keyword fields
- **Scoring profiles**: boost by magnitude, distance, freshness, or tag match

### Search Request — the 5 query modes
| Mode | How | Key params |
|------|-----|-----------|
| **Keyword** | `search` + `queryType=simple` | filter, orderby, top, skip, facets |
| **Full Lucene** | `search` + `queryType=full` | field:value, wildcards, fuzzy~, proximity"N" |
| **Vector** | `vectorQueries` (text/image/raw) | k, fields, oversampling, threshold |
| **Hybrid** | `search` + `vectorQueries` together | vectorFilterMode, hybridSearch.maxTextRecallSize |
| **Semantic** | any above + `queryType=semantic` | semanticConfiguration, answers, captions, queryRewrites |

### Indexer Pipeline — the 4 resources
```
DataSource  →  Indexer  →  (Skillset)  →  Index
   ↑              ↑            ↑
 blob/sql/    schedule,    skills[],
 cosmos/etc   fieldMappings  indexProjection,
              parameters     knowledgeStore
```

**Data source types**: azuresql, cosmosdb, azureblob, azuretable, mysql, adlsgen2, onelake, sharepoint

**Parsing modes**: default, text, delimitedText, json, jsonArray, jsonLines, markdown (oneToMany | oneToOne)

### Skills — 4 categories
| Category | Skills |
|----------|--------|
| **Text analysis** | KeyPhrase, EntityRecognitionV3, EntityLinking, SentimentV3, LanguageDetection, Translation, CustomEntityLookup, PIIDetection |
| **Text processing** | SplitSkill, MergeSkill, ConditionalSkill, ShaperSkill, DocumentExtractionSkill |
| **Embedding & LLM** | AzureOpenAIEmbeddingSkill, ChatCompletionSkill, WebApiSkill, AzureMachineLearningSkill |
| **Vision & Doc Intelligence** | OcrSkill, ImageAnalysisSkill, VisionVectorizeSkill, DocumentIntelligenceLayoutSkill, ContentUnderstandingSkill |

### Index Projections (chunking pipelines)
> SplitSkill + EmbeddingSkill → MUST use `indexProjection` on skillset, NOT `outputFieldMappings`

- Set on `skillset.indexProjection` (singular in Python SDK)
- Selector: targetIndexName, parentKeyFieldName, sourceContext (`/document/chunks/*`), mappings
- Target index key field MUST have `analyzer: "keyword"`
- Target index MUST have `parent_id` field (Edm.String, filterable)
- `projectionMode`: skipIndexingParentDocuments | includeIndexingParentDocuments
- Creation order: DataSource → Index → Skillset (with projection) → Indexer (no field/output mappings)

### Knowledge Bases (agentic retrieval)
- Attach `KnowledgeSources` (search index, blob, SharePoint, OneLake, web)
- Configure LLM model for query planning (Azure OpenAI)
- `retrieve` endpoint: send messages → multi-hop reasoning → references + answer
- `reasoningEffort`: minimal | low | medium
- `outputMode`: extractiveData | answerSynthesis

### Vector Search Config Stack
```
VectorSearch
  ├── algorithms[]        → HNSW or ExhaustiveKNN (metric: cosine|euclidean|dotProduct|hamming)
  ├── profiles[]          → ties algorithm + vectorizer + compression together
  ├── vectorizers[]       → AzureOpenAI | AIServicesVision | AML | WebApi
  └── compressions[]      → ScalarQuantization (int8) | BinaryQuantization
```

### Security
- **API keys**: admin (full CRUD) or query (read-only search)
- **OAuth 2.0**: Azure Entra ID bearer tokens
- **CMK encryption**: `SearchResourceEncryptionKey` on index/skillset/datasource/etc.
- **Managed identity**: system-assigned or user-assigned for indexer data access
- **Document-level**: permission filter fields (userIds/groupIds/rbacScope)

---

## Key Enums (cheat sheet)

| Enum | Values |
|------|--------|
| **Field types** | Edm.String, Int32, Int64, Double, Single, Half, Boolean, DateTimeOffset, GeographyPoint, ComplexType, Int16, SByte, Byte + Collection() |
| **Vector metrics** | cosine, euclidean, dotProduct, hamming |
| **Query types** | simple, full, semantic |
| **Index actions** | upload, merge, mergeOrUpload, delete |
| **Indexer status** | unknown, error, running |
| **Execution status** | transientFailure, success, inProgress, reset |
| **Parsing modes** | default, text, delimitedText, json, jsonArray, jsonLines, markdown |
| **Data sources** | azuresql, cosmosdb, azureblob, azuretable, mysql, adlsgen2, onelake, sharepoint |
| **Vector filter** | postFilter, preFilter, strictPostFilter |
| **Projection mode** | skipIndexingParentDocuments, includeIndexingParentDocuments |
| **Semantic errors** | partial, fail |
| **Debug modes** | disabled, semantic, vector, queryRewrites, innerHits, all |
| **Scoring agg** | sum, average, minimum, maximum, firstMatching, product |
| **KB reasoning** | minimal, low, medium |
| **KB output** | extractiveData, answerSynthesis |
| **KB sources** | searchIndex, azureBlob, indexedSharePoint, remoteSharePoint, indexedOneLake, web |
| **Autocomplete** | oneTerm, twoTerms, oneTermWithContext |
| **Embedding models** | text-embedding-ada-002, 3-small, 3-large |
| **Chat models** | gpt-35-turbo, gpt-4, gpt-4o, gpt-4o-mini, gpt-4.1, gpt-4.1-mini, gpt-5 |
