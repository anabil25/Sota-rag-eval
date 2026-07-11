# Azure AI Search REST API Reference Overview

> Source: `search.json` swagger — API version `2025-11-01-preview`
> 38 paths, 421 type definitions

---

## Index Management

| Path | Methods | Operations |
|------|---------|-----------|
| `/indexes` | GET, POST | List indexes • Create index |
| `/indexes?_overload=listWithSelectedProperties` | GET | List indexes with `$select` field filtering |
| `/indexes('{indexName}')` | GET, PUT, DELETE | Get index • Create/update index • Delete index |
| `/indexes('{indexName}')/search.stats` | GET | Get index statistics (doc count, storage size, vector index size) |
| `/indexes('{indexName}')/search.analyze` | POST | Test how an analyzer breaks text into tokens |
| `/indexstats` | GET | Summary stats across all indexes |

### Index Definition (`SearchIndex`)
| Property | Type | Notes |
|----------|------|-------|
| `name` | string | Index name |
| `fields` | `SearchField[]` | Field definitions (required) |
| `scoringProfiles` | `ScoringProfile[]` | Custom relevance boosting |
| `defaultScoringProfile` | string | Profile applied by default |
| `suggesters` | `SearchSuggester[]` | Autocomplete/suggest configs |
| `corsOptions` | `CorsOptions` | Cross-origin resource sharing (allowedOrigins, maxAgeInSeconds) |
| `analyzers` | `LexicalAnalyzer[]` | Custom analyzers |
| `tokenizers` | `LexicalTokenizer[]` | Custom tokenizers |
| `tokenFilters` | `TokenFilter[]` | Custom token filters |
| `charFilters` | `CharFilter[]` | Custom character filters |
| `normalizers` | `LexicalNormalizer[]` | Custom normalizers |
| `similarity` | `SimilarityAlgorithm` | BM25 or Classic TF-IDF |
| `semantic` | `SemanticSearch` | Semantic search configs |
| `vectorSearch` | `VectorSearch` | Vector algorithms, profiles, vectorizers, compression |
| `encryptionKey` | `SearchResourceEncryptionKey` | Customer-managed Key Vault encryption |
| `permissionFilterOption` | enabled \| disabled | Document-level security |

### Field Definition (`SearchField`)
| Property | Type | Notes |
|----------|------|-------|
| `name` | string | Field name |
| `type` | `SearchFieldDataType` | Data type (see enum below) |
| `key` | bool | Document key field (exactly one per index) |
| `searchable` | bool | Full-text searchable |
| `filterable` | bool | Allowed in `$filter` |
| `sortable` | bool | Allowed in `$orderby` |
| `facetable` | bool | Allowed in `facet` |
| `retrievable` | bool | Returned in results (REST only — Python SDK uses `hidden` instead) |
| `stored` | bool | Physically stored (if false, not retrievable) |
| `analyzer` | string | Analyzer for both indexing and querying |
| `searchAnalyzer` | string | Query-time analyzer override |
| `indexAnalyzer` | string | Index-time analyzer override |
| `normalizer` | string | Normalizer for filterable/sortable fields |
| `synonymMaps` | string[] | Synonym map references |
| `vectorSearchDimensions` | int | Vector dimension count |
| `vectorSearchProfile` | string | Vector search profile reference |
| `vectorEncoding` | `VectorEncodingFormat` | packedBit |
| `permissionFilter` | `PermissionFilter` | userIds \| groupIds \| rbacScope |
| `fields` | `SearchField[]` | Sub-fields for `Edm.ComplexType` |

### `SearchFieldDataType` Enum
| Type | Description |
|------|-------------|
| `Edm.String` | Unicode text |
| `Edm.Int32` | 32-bit integer |
| `Edm.Int64` | 64-bit integer |
| `Edm.Double` | 64-bit float |
| `Edm.Single` | 32-bit float |
| `Edm.Half` | 16-bit float (vectors) |
| `Edm.Boolean` | true/false |
| `Edm.DateTimeOffset` | Date/time |
| `Edm.GeographyPoint` | Lat/lon |
| `Edm.ComplexType` | Nested structure |
| `Edm.Int16` | 16-bit integer |
| `Edm.SByte` | Signed byte (int8, used for scalar quantized vectors) |
| `Edm.Byte` | Unsigned byte (binary quantized vectors) |
| `Collection(Edm.*)` | Array of any above type |

### Other Index Types
- `SearchSuggester` — name, searchMode, sourceFields
- `CorsOptions` — allowedOrigins, maxAgeInSeconds
- `SearchAlias` — name, indexes[] (route queries without changing client code)
- `GetIndexStatisticsResult` — documentCount, storageSize, vectorIndexSize
- `IndexStatisticsSummary` — summary across all indexes
- `SearchServiceStatistics` — `SearchServiceCounters` + `SearchServiceLimits`
- `SearchServiceCounters` — indexCount, documentCount, storageSizeInBytes (each as `ResourceCounter` with usage + quota)
- `SearchServiceLimits` — maxFieldsPerIndex, maxFieldNestingDepthPerIndex, maxComplexCollectionFieldsPerIndex, maxComplexObjectsInCollectionsPerIndex
- `AnalyzeRequest` — text, analyzer (or tokenizer + tokenFilters + charFilters)
- `AnalyzeResult` — `AnalyzedTokenInfo[]` (token, startOffset, endOffset, position)

---

## Document Operations

| Path | Methods | Operations |
|------|---------|-----------|
| `/indexes('{indexName}')/docs` | GET | Search documents (GET with query string params) |
| `/indexes('{indexName}')/docs/search.post.search` | POST | Search documents (POST with JSON body) |
| `/indexes('{indexName}')/docs/$count` | GET | Get document count |
| `/indexes('{indexName}')/docs('{key}')` | GET | Lookup single document by key |
| `/indexes('{indexName}')/docs/search.suggest` | GET | Suggest (GET) |
| `/indexes('{indexName}')/docs/search.post.suggest` | POST | Suggest (POST) |
| `/indexes('{indexName}')/docs/search.autocomplete` | GET | Autocomplete (GET) |
| `/indexes('{indexName}')/docs/search.post.autocomplete` | POST | Autocomplete (POST) |
| `/indexes('{indexName}')/docs/search.index` | POST | Batch document actions (upload/merge/delete) |

### Search Request (`SearchRequest`)
| Property | Type | Notes |
|----------|------|-------|
| `search` | string | Query text |
| `searchMode` | any \| all | Match any or all terms |
| `searchFields` | string | Comma-separated fields to search |
| `queryType` | simple \| full \| semantic | Lucene simple, full syntax, or semantic |
| `filter` | string | OData `$filter` expression |
| `orderby` | string | `$orderby` expression |
| `select` | string | `$select` — fields to return |
| `top` | int | Max results to return |
| `skip` | int | Offset for paging |
| `count` | bool | Include total count |
| `facets` | string[] | Facet expressions |
| `highlight` | string | Fields for hit highlighting |
| `highlightPreTag` | string | HTML tag before highlights |
| `highlightPostTag` | string | HTML tag after highlights |
| `minimumCoverage` | double | Min % of index that must be queried |
| `scoringProfile` | string | Scoring profile to apply |
| `scoringParameters` | string[] | Scoring function params |
| `scoringStatistics` | local \| global | Score calculation scope |
| `sessionId` | string | Sticky session for scoring consistency |
| `vectorQueries` | `VectorQuery[]` | Vector search queries |
| `vectorFilterMode` | postFilter \| preFilter \| strictPostFilter | When to apply filters |
| `semanticConfiguration` | string | Semantic config name |
| `semanticQuery` | string | Separate text for semantic ranking |
| `semanticFields` | string | Fields for semantic processing |
| `semanticErrorHandling` | `SemanticErrorMode` (partial \| fail) | What to do on semantic errors |
| `semanticMaxWaitInMilliseconds` | int | Timeout for semantic processing |
| `answers` | `QueryAnswerType` (none \| extractive) | Extractive Q&A |
| `captions` | `QueryCaptionType` (none \| extractive) | Extractive summaries |
| `queryRewrites` | `QueryRewritesType` (none \| generative) | AI query rewriting |
| `queryLanguage` | `QueryLanguage` | 65+ locale codes (e.g., en-us, fr-fr) |
| `speller` | none \| lexicon | Spell correction |
| `hybridSearch` | `HybridSearch` | Hybrid search config |
| `debug` | `QueryDebugMode` | disabled \| semantic \| vector \| queryRewrites \| innerHits \| all |

### Hybrid Search (`HybridSearch`)
| Property | Type | Notes |
|----------|------|-------|
| `maxTextRecallSize` | int | Max docs from keyword leg before RRF fusion |
| `countAndFacetMode` | `HybridCountAndFacetMode` | countRetrievableResults \| countAllResults |

### Search Response (`SearchDocumentsResult`)
| Property | Type | Notes |
|----------|------|-------|
| `value` | `SearchResult[]` | Per-document results |
| `@odata.count` | long | Total matching documents (if `count=true`) |
| `@search.coverage` | double | % of index searched |
| `@search.facets` | `FacetResult[]` | Facet buckets |
| `@search.answers` | `QueryAnswerResult[]` | Extractive Q&A answers |
| `@search.debug` | `DebugInfo` | Debug information (if enabled) |
| `@odata.nextLink` | string | Continuation URL |
| `@search.nextPageParameters` | `SearchRequest` | Continuation request body |
| `@search.semanticPartialResponseReason` | `SemanticErrorReason` | Why semantic was partial |
| `@search.semanticPartialResponseType` | `SemanticSearchResultsType` | What partial results include |
| `@search.semanticQueryRewritesResultType` | `SemanticQueryRewritesResultType` | Rewrite result type |

### Per-Document Result (`SearchResult`)
| Property | Type | Notes |
|----------|------|-------|
| `@search.score` | double | RRF or BM25 score |
| `@search.rerankerScore` | double | Semantic reranker score |
| `@search.rerankerBoostedScore` | double | Boosted reranker score |
| `@search.highlights` | dict | Hit-highlighted excerpts per field |
| `@search.captions` | `QueryCaptionResult[]` | Extracted captions |
| `@search.documentDebugInfo` | `DocumentDebugInfo` | Debug details per document |
| (document fields) | any | All selected fields from the index |

### Facet Results (`FacetResult`)
Properties: count, value, from, to — plus aggregations: sum, avg, min, max, cardinality; supports nested facets

### Suggest (`SuggestRequest` / `SuggestDocumentsResult`)
- `SuggestRequest` — search, suggesterName, filter, orderby, select, searchFields, top, minimumCoverage, fuzzy, highlightPreTag/PostTag
- `SuggestDocumentsResult` — value (`SuggestResult[]`: text, @search.text, document fields), @search.coverage

### Autocomplete (`AutocompleteRequest` / `AutocompleteResult`)
- `AutocompleteRequest` — search, suggesterName, autocompleteMode, filter, fuzzy, highlightPreTag/PostTag, minimumCoverage, searchFields, top
- `AutocompleteMode` — oneTerm | twoTerms | oneTermWithContext
- `AutocompleteResult` — value (`AutocompleteItem[]`: text, queryPlusText), @search.coverage

### Batch Indexing (`IndexBatch` / `IndexDocumentsResult`)
- `IndexBatch` — value (`IndexAction[]`: @search.action + document fields)
- `IndexActionType` — upload | merge | mergeOrUpload | delete
- `IndexDocumentsResult` — value (`IndexingResult[]`: key, status, statusCode, errorMessage)

---

## Indexer Pipeline

| Path | Methods | Operations |
|------|---------|-----------|
| `/datasources` | GET, POST | List/create datasources |
| `/datasources('{name}')` | GET, PUT, DELETE | Get/update/delete datasource |
| `/indexers` | GET, POST | List/create indexers |
| `/indexers('{name}')` | GET, PUT, DELETE | Get/update/delete indexer |
| `/indexers('{name}')/search.run` | POST | Run indexer on-demand |
| `/indexers('{name}')/search.status` | GET | Get indexer status & execution history |
| `/indexers('{name}')/search.reset` | POST | Reset change tracking state |
| `/indexers('{name}')/search.resetdocs` | POST | Reset specific docs for re-indexing (`DocumentKeysOrIds`) |
| `/indexers('{name}')/search.resync` | POST | Resync permission data (`IndexerResyncBody`, options: allDocumentsExceptManuallyReset \| allDocuments) |
| `/skillsets` | GET, POST | List/create skillsets |
| `/skillsets('{name}')` | GET, PUT, DELETE | Get/update/delete skillset |
| `/skillsets('{name}')/search.resetskills` | POST | Reset individual skills (`SkillNames`) |
| `/synonymmaps` | GET, POST | List/create synonym maps |
| `/synonymmaps('{name}')` | GET, PUT, DELETE | Get/update/delete synonym map |

### Data Source (`SearchIndexerDataSource`)
| Property | Type | Notes |
|----------|------|-------|
| `name` | string | Data source name |
| `type` | `SearchIndexerDataSourceType` | See enum below |
| `credentials` | `DataSourceCredentials` | connectionString or ResourceId |
| `container` | `SearchIndexerDataContainer` | name, query (optional) |
| `identity` | `SearchIndexerDataIdentity` | Managed identity override |
| `dataChangeDetectionPolicy` | `DataChangeDetectionPolicy` | Change tracking |
| `dataDeletionDetectionPolicy` | `DataDeletionDetectionPolicy` | Soft-delete detection |
| `encryptionKey` | `SearchResourceEncryptionKey` | CMK encryption |

**`SearchIndexerDataSourceType`** — azuresql | cosmosdb | azureblob | azuretable | mysql | adlsgen2 | onelake | sharepoint

### Indexer (`SearchIndexer`)
| Property | Type | Notes |
|----------|------|-------|
| `name` | string | Indexer name |
| `dataSourceName` | string | Data source reference |
| `targetIndexName` | string | Target index |
| `skillsetName` | string | Optional skillset |
| `parameters` | `IndexingParameters` | Indexer config |
| `fieldMappings` | `FieldMapping[]` | Source → index field mapping |
| `outputFieldMappings` | `FieldMapping[]` | Enriched output → index field mapping |
| `schedule` | `IndexingSchedule` | interval (ISO 8601 duration), startTime |
| `disabled` | bool | Pause indexer |
| `cache` | `SearchIndexerCache` | Enrichment cache (storageConnectionString, enableReprocessing) |
| `encryptionKey` | `SearchResourceEncryptionKey` | CMK encryption |

### Indexing Parameters (`IndexingParameters`)
Key `configuration` properties:
| Property | Type | Notes |
|----------|------|-------|
| `parsingMode` | `BlobIndexerParsingMode` | default \| text \| delimitedText \| json \| jsonArray \| jsonLines \| markdown |
| `markdownParsingSubmode` | `MarkdownParsingSubmode` | oneToMany \| oneToOne |
| `markdownHeaderDepth` | `MarkdownHeaderDepth` | h1 through h6 |
| `dataToExtract` | `BlobIndexerDataToExtract` | storageMetadata \| allMetadata \| contentAndMetadata |
| `imageAction` | `BlobIndexerImageAction` | none \| generateNormalizedImages \| generateNormalizedImagePerPage |
| `pdfTextRotationAlgorithm` | `BlobIndexerPDFTextRotationAlgorithm` | none \| detectAngles |
| `executionEnvironment` | `IndexerExecutionEnvironment` | standard \| private |
| `indexingMode` | `IndexingMode` | indexingAllDocs \| indexingResetDocs |

### Field Mapping (`FieldMapping`)
- `sourceFieldName` — source field
- `targetFieldName` — destination index field
- `mappingFunction` — `FieldMappingFunction` (name, parameters). Functions: base64Encode, base64Decode, extractTokenAtPosition, jsonArrayToStringCollection, urlEncode, urlDecode, fixedLengthHash

### Change / Delete Detection Policies
- `HighWaterMarkChangeDetectionPolicy` — highWaterMarkColumnName
- `SqlIntegratedChangeTrackingPolicy` — SQL Server change tracking
- `SoftDeleteColumnDeletionDetectionPolicy` — softDeleteColumnName, softDeleteMarkerValue
- `NativeBlobSoftDeleteDeletionDetectionPolicy` — Azure Blob native soft delete

### Indexer Status (`SearchIndexerStatus`)
- `status` — `IndexerStatus` (unknown | error | running)
- `lastResult` — `IndexerExecutionResult`
- `executionHistory` — `IndexerExecutionResult[]`
- `limits` — `SearchIndexerLimits` (maxRunTime, maxDocumentExtractionSize, maxDocumentContentCharactersToExtract)

### Indexer Execution (`IndexerExecutionResult`)
| Property | Type | Notes |
|----------|------|-------|
| `status` | `IndexerExecutionStatus` | transientFailure \| success \| inProgress \| reset |
| `statusDetail` | `IndexerExecutionStatusDetail` | resetDocs \| indexingMode details |
| `currentState` | `IndexerCurrentState` | mode, allDocsCount, processedCount |
| `errors` | `SearchIndexerError[]` | key, errorMessage, statusCode, name, details, documentationLink |
| `warnings` | `SearchIndexerWarning[]` | key, message, name, details, documentationLink |
| `itemCount` | int | Total items processed |
| `failedItemCount` | int | Items that failed |
| `initialTrackingState` | string | Change tracking start |
| `finalTrackingState` | string | Change tracking end |

---

## Skillset Definition (`SearchIndexerSkillset`)

| Property | Type | Notes |
|----------|------|-------|
| `name` | string | Skillset name |
| `skills` | `SearchIndexerSkill[]` | Array of skills |
| `cognitiveServices` | `CognitiveServicesAccount` | AI services binding (legacy) |
| `knowledgeStore` | `SearchIndexerKnowledgeStore` | Knowledge store projections |
| `indexProjection` | `SearchIndexerIndexProjection` | **Index projections** (see below) |
| `encryptionKey` | `SearchResourceEncryptionKey` | CMK encryption |

### Skill I/O Mapping
- `InputFieldMappingEntry` — name, source, sourceContext, inputs (for nested mappings)
- `OutputFieldMappingEntry` — name, targetName

### AI Services Binding
- `CognitiveServicesAccount` — base type (discriminator)
  - `AIServicesAccountIdentity` — subdomainUrl, identity (managed identity auth)
  - `AIServicesAccountKey` — key, subdomainUrl
  - `CognitiveServicesAccountKey` — key (legacy)
  - `DefaultCognitiveServicesAccount` — free tier

---

## Index Projections (CRITICAL for chunking pipelines)

> When using SplitSkill + EmbeddingSkill, you MUST use index projections.
> Do NOT use `outputFieldMappings` for chunked/embedded data — causes `Collection(Edm.Double)` vs `Collection(Edm.Single)` type mismatches.

### `SearchIndexerIndexProjection`
| Property | Type | Notes |
|----------|------|-------|
| `selectors` | `SearchIndexerIndexProjectionSelector[]` | One per target index |
| `parameters` | `SearchIndexerIndexProjectionsParameters` | Global projection settings |

### `SearchIndexerIndexProjectionSelector`
| Property | Type | Notes |
|----------|------|-------|
| `targetIndexName` | string | Index to project into (MUST exist before skillset creation) |
| `parentKeyFieldName` | string | Field in target index for parent doc key (e.g., `parent_id`) |
| `sourceContext` | string | Enrichment path (e.g., `/document/chunks/*`) |
| `mappings` | `InputFieldMappingEntry[]` | Field mappings from enrichment tree to index fields |

### `SearchIndexerIndexProjectionsParameters`
| Property | Type | Notes |
|----------|------|-------|
| `projectionMode` | `IndexProjectionMode` | skipIndexingParentDocuments \| includeIndexingParentDocuments |

### Index Schema Requirements for Projections
- Key field **must** have `analyzer: "keyword"` — projections generate composite keys
- Index **must** have a `parent_id` field (Edm.String, filterable)
- Python SDK attribute is `index_projection` (singular), NOT `index_projections`

---

## Knowledge Store

### `SearchIndexerKnowledgeStore`
| Property | Type | Notes |
|----------|------|-------|
| `storageConnectionString` | string | Azure Storage connection |
| `projections` | `SearchIndexerKnowledgeStoreProjection[]` | Projection definitions |
| `parameters` | `SearchIndexerKnowledgeStoreParameters` | Store settings |
| `identity` | `SearchIndexerDataIdentity` | Managed identity |

### `SearchIndexerKnowledgeStoreProjection`
| Property | Type | Notes |
|----------|------|-------|
| `tables` | `SearchIndexerKnowledgeStoreTableProjectionSelector[]` | Project to Azure Table Storage |
| `objects` | `SearchIndexerKnowledgeStoreObjectProjectionSelector[]` | Project to Blob Storage (JSON) |
| `files` | `SearchIndexerKnowledgeStoreFileProjectionSelector[]` | Project to Blob Storage (binary) |

Each selector has: tableName/storageContainer, source, sourceContext, inputs, generatedKeyName, referenceKeyName

---

## Skills (AI Enrichment)

### Text Analysis Skills
| Skill | Description | Key Properties |
|-------|-------------|----------------|
| `KeyPhraseExtractionSkill` | Extract key phrases | defaultLanguageCode, maxKeyPhraseCount, modelVersion |
| `EntityRecognitionSkillV3` | Named entity recognition | categories, defaultLanguageCode, minimumPrecision, modelVersion |
| `EntityLinkingSkill` | Link entities to knowledge base | defaultLanguageCode, minimumPrecision, modelVersion |
| `SentimentSkillV3` | Sentiment analysis | defaultLanguageCode, modelVersion, includeOpinionMining |
| `LanguageDetectionSkill` | Detect language | defaultCountryHint, modelVersion |
| `TextTranslationSkill` | Translate text | defaultFromLanguageCode, defaultToLanguageCode, suggestedFrom |
| `CustomEntityLookupSkill` | Match against custom entity list | entitiesDefinitionUri, inlineEntitiesDefinition, defaultLanguageCode, globalDefaultCaseSensitive, globalDefaultFuzzyEditDistance |
| `PIIDetectionSkill` | Detect/mask PII | defaultLanguageCode, minimumPrecision, maskingMode (none \| replace), maskingCharacter, modelVersion, piiCategories, domain |

### Text Processing Skills
| Skill | Description | Key Properties |
|-------|-------------|----------------|
| `SplitSkill` | Chunk text | textSplitMode (pages \| sentences), maximumPageLength, pageOverlapLength, maximumPagesToTake, unit (characters \| azureOpenAITokens), azureOpenAITokenizerParameters (encoderModelName: r50k_base \| p50k_base \| p50k_edit \| cl100k_base), defaultLanguageCode |
| `MergeSkill` | Merge strings | insertPreTag, insertPostTag |
| `ConditionalSkill` | Boolean operations | (uses I/O mappings) |
| `ShaperSkill` | Reshape into complex types | (uses I/O mappings) |
| `DocumentExtractionSkill` | Extract text from files | parsingMode, dataToExtract |

### Embedding & LLM Skills
| Skill | Description | Key Properties |
|-------|-------------|----------------|
| `AzureOpenAIEmbeddingSkill` | Generate embeddings | resourceUri, deploymentId, modelName, dimensions, apiKey, authIdentity |
| `ChatCompletionSkill` | Call Azure OpenAI Chat API | See detailed breakdown below |
| `WebApiSkill` | Call custom HTTP endpoint | uri, httpMethod, httpHeaders, timeout, batchSize, degreeOfParallelism |
| `AzureMachineLearningSkill` | Call Azure ML endpoint | uri, key, resourceId, timeout, region, degreeOfParallelism |

### Vision Skills
| Skill | Description | Key Properties |
|-------|-------------|----------------|
| `OcrSkill` | Extract text from images | defaultLanguageCode, detectOrientation, lineEnding (space \| carriageReturn \| lineFeed \| carriageReturnLineFeed) |
| `ImageAnalysisSkill` | Analyze images | defaultLanguageCode, visualFeatures (adult \| brands \| categories \| description \| faces \| objects \| tags) |
| `VisionVectorizeSkill` | Image/text embeddings | modelVersion |

### Document Intelligence Skills
| Skill | Description | Key Properties |
|-------|-------------|----------------|
| `DocumentIntelligenceLayoutSkill` | Layout analysis | outputFormat (text \| markdown), outputMode (oneToMany \| oneToOne), markdownHeaderDepth (h1-h6), chunkingProperties (unit, maximumLength, overlapLength) |
| `ContentUnderstandingSkill` | Structured extraction | chunkingProperties, extractionOptions |

### ChatCompletionSkill — Full Detail
| Property | Type | Notes |
|----------|------|-------|
| `uri` | string | Azure OpenAI endpoint URL |
| `apiKey` | string | API key (null for managed identity) |
| `authResourceId` | string | `https://cognitiveservices.azure.com` for MI auth |
| `authIdentity` | `SearchIndexerDataIdentity` | Managed identity |
| `httpMethod` | string | POST |
| `httpHeaders` | `WebApiHttpHeaders` | Custom HTTP headers |
| `timeout` | duration | Request timeout |
| `batchSize` | int | Documents per batch |
| `degreeOfParallelism` | int | Concurrent requests |
| `commonModelParameters` | `ChatCompletionCommonModelParameters` | model, temperature, maxTokens, frequencyPenalty, presencePenalty, seed, stop |
| `extraParameters` | string | Additional model params |
| `extraParametersBehavior` | `ChatCompletionExtraParametersBehavior` | passThrough \| drop \| error |
| `responseFormat` | `ChatCompletionResponseFormat` | See below |

### ChatCompletion Response Format
- `ChatCompletionResponseFormatType` — text | jsonObject | jsonSchema
- `ChatCompletionResponseFormat` — type + jsonSchemaProperties
- `ChatCompletionSchema` / `ChatCompletionSchemaProperties` — Structured JSON schema output

---

## Vector Search

### Algorithms
| Type | Description | Parameters |
|------|-------------|------------|
| `HnswAlgorithmConfiguration` | Hierarchical Navigable Small World (approx NN) | m (4-10), efConstruction (100-1000), efSearch (100-1000), metric |
| `ExhaustiveKnnAlgorithmConfiguration` | Brute-force exact NN | metric |

**`VectorSearchAlgorithmMetric`** — cosine | euclidean | dotProduct | hamming

### Vectorizers
| Type | Description | Key Parameters |
|------|-------------|----------------|
| `AzureOpenAIVectorizer` | Azure OpenAI embeddings | resourceUrl, deploymentName, modelName, apiKey, authIdentity |
| `AIServicesVisionVectorizer` | AI Services Vision multimodal | resourceUri, modelVersion, apiKey, authIdentity |
| `AMLVectorizer` | Azure ML endpoint | uri, key, resourceId, timeout, modelName |
| `WebApiVectorizer` | Custom HTTP endpoint | uri, httpMethod, httpHeaders, timeout, authResourceId, authIdentity |

### Profiles & Compression
- `VectorSearchProfile` — name, algorithmConfigurationName, vectorizerName, compressionName
- `ScalarQuantizationCompression` — quantizedDataType (int8), rescoring options
- `BinaryQuantizationCompression` — binary quantization with optional rescoring
- `RescoringOptions` — enableRescoring, defaultOversampling, rescoreStorageMethod (preserveOriginals \| discardOriginals)

### Vector Query Types
| Type | Description | Key Properties |
|------|-------------|----------------|
| `VectorQuery` (base) | Common vector query fields | kind, k, fields, exhaustive, oversampling, weight, threshold, filterOverride, perDocumentVectorLimit |
| `VectorizedQuery` | Pre-computed vector | vector (float[]) |
| `VectorizableTextQuery` | Text → auto-vectorized | text |
| `VectorizableImageUrlQuery` | Image URL → auto-vectorized | url |
| `VectorizableImageBinaryQuery` | Base64 image → auto-vectorized | binaryData |

### Vector Thresholds
- `VectorThreshold` (base) — `VectorThresholdKind` discriminator
  - `VectorSimilarityThreshold` — value (0-1, cosine similarity cutoff)
  - `SearchScoreThreshold` — value (min score cutoff)

**`VectorFilterMode`** — postFilter | preFilter | strictPostFilter

---

## Semantic Search

### Configuration
- `SemanticSearch` — configurations (`SemanticConfiguration[]`), defaultConfiguration
- `SemanticConfiguration` — name, prioritizedFields, rankingOrder
- `SemanticPrioritizedFields` — titleField, prioritizedContentFields, prioritizedKeywordsFields
- `SemanticField` — fieldName
- `RankingOrder` — BoostedRerankerScore | RerankerScore

### Query Parameters
| Parameter | Type | Notes |
|-----------|------|-------|
| `semanticConfiguration` | string | Config name |
| `answers` | none \| extractive | Extractive Q&A |
| `captions` | none \| extractive | Extractive summaries |
| `queryRewrites` | none \| generative | AI query rewriting |
| `queryLanguage` | `QueryLanguage` | 65+ locale codes for semantic processing |
| `speller` | `QuerySpellerType` | none \| lexicon |
| `semanticErrorHandling` | `SemanticErrorMode` | partial \| fail |
| `semanticMaxWaitInMilliseconds` | int | Semantic timeout |

### Response Fields
| Field | Type | Notes |
|-------|------|-------|
| `@search.rerankerScore` | double | Semantic relevance score |
| `@search.captions` | `QueryCaptionResult[]` | text, highlights, additionalProperties |
| `@search.answers` | `QueryAnswerResult[]` | text, highlights, key, score, additionalProperties |
| `@search.semanticPartialResponseReason` | `SemanticErrorReason` | capacityOverloaded \| transient \| maxWaitExceeded |

### Debug (`QueryDebugMode`)
disabled | semantic | vector | queryRewrites | innerHits | all

---

## Knowledge Bases / Agentic Retrieval

| Path | Methods | Operations |
|------|---------|-----------|
| `/knowledgebases` | GET, POST | List/create KBs |
| `/knowledgebases('{name}')` | GET, PUT, DELETE | Get/update/delete KB |
| `/knowledgebases('{name}')/retrieve` | POST | Agentic retrieval with multi-hop reasoning |
| `/knowledgesources` | GET, POST | List/create knowledge sources |
| `/knowledgesources('{name}')` | GET, PUT, DELETE | Get/update/delete source |
| `/knowledgesources('{name}')/status` | GET | Source sync status |

### Knowledge Base (`KnowledgeBase`)
| Property | Type | Notes |
|----------|------|-------|
| `name` | string | KB name |
| `description` | string | Human-readable description |
| `knowledgeSources` | `KnowledgeSourceReference[]` | Attached sources |
| `models` | `KnowledgeBaseModel[]` | LLM for query planning |
| `retrievalReasoningEffort` | `KnowledgeRetrievalReasoningEffort` | minimal \| low \| medium |
| `outputMode` | `KnowledgeRetrievalOutputMode` | extractiveData \| answerSynthesis |
| `retrievalInstructions` | string | Custom retrieval instructions |
| `answerInstructions` | string | Custom answer synthesis instructions |
| `encryptionKey` | `SearchResourceEncryptionKey` | CMK encryption |

### Knowledge Base Model (`KnowledgeBaseModel`)
- `KnowledgeBaseModelKind` — azureOpenAI (for query planner)
- `KnowledgeBaseAzureOpenAIModel` — azureOpenAIParameters (resourceUri, deploymentId, modelName, apiKey, authIdentity)

### Retrieval Request (`KnowledgeBaseRetrievalRequest`)
| Property | Type | Notes |
|----------|------|-------|
| `messages` | `KnowledgeBaseMessage[]` | Conversation messages |
| `intents` | `KnowledgeRetrievalIntent[]` | Explicit query intents |
| `maxRuntimeInSeconds` | int | Timeout |
| `maxOutputSize` | int | Max output size |
| `retrievalReasoningEffort` | `KnowledgeRetrievalReasoningEffort` | Override KB default |
| `outputMode` | `KnowledgeRetrievalOutputMode` | Override KB default |
| `includeActivity` | bool | Include planning activity trace |
| `knowledgeSourceParams` | `KnowledgeSourceParams[]` | Per-source runtime params |

### Retrieval Messages
- `KnowledgeBaseMessage` — role (user \| assistant), content
- `KnowledgeBaseMessageContent` — `KnowledgeBaseMessageContentType` discriminator
  - `KnowledgeBaseMessageTextContent` — text
  - `KnowledgeBaseMessageImageContent` — url or data (base64)

### Retrieval Response (`KnowledgeBaseRetrievalResponse`)
- `KnowledgeBaseRetrievalSuccessResponse` — response (text), references, activity
- `KnowledgeBaseRetrievalPartialResponse` — partial results with errors

### Retrieval Intents
- `KnowledgeRetrievalIntent` — `KnowledgeRetrievalIntentType` discriminator
  - `KnowledgeRetrievalSemanticIntent` — query text for semantic search

### References (per source type)
`KnowledgeBaseReference` (base) → `KnowledgeBaseReferenceType` discriminator:
- `KnowledgeBaseSearchIndexReference` — indexName, documentKey, fieldName, content, score
- `KnowledgeBaseAzureBlobReference` — storageAccountName, containerName, blobName, content
- `KnowledgeBaseIndexedOneLakeReference` — content, score
- `KnowledgeBaseIndexedSharePointReference` — url, content
- `KnowledgeBaseRemoteSharePointReference` — url, content
- `KnowledgeBaseWebReference` — url, content

### Activity Records
`KnowledgeBaseActivityRecord` (base) → `KnowledgeBaseActivityRecordType` discriminator:
- `KnowledgeBaseModelQueryPlanningActivityRecord` — LLM query decomposition
- `KnowledgeBaseSearchIndexActivityRecord` — Search index retrieval (query, filter, select, top, vectorQueries)
- `KnowledgeBaseAzureBlobActivityRecord` — Blob retrieval
- `KnowledgeBaseIndexedOneLakeActivityRecord` — OneLake retrieval
- `KnowledgeBaseIndexedSharePointActivityRecord` — SharePoint indexed retrieval
- `KnowledgeBaseRemoteSharePointActivityRecord` — SharePoint native retrieval
- `KnowledgeBaseWebActivityRecord` — Web search retrieval
- `KnowledgeBaseAgenticReasoningActivityRecord` — Chain-of-thought reasoning
- `KnowledgeBaseModelAnswerSynthesisActivityRecord` — LLM answer generation

### Knowledge Source Types
| Type | Description | Key Parameters |
|------|-------------|----------------|
| `SearchIndexKnowledgeSource` | Index-backed | indexName, queryType, semanticConfiguration, top, filter, select |
| `AzureBlobKnowledgeSource` | Blob w/ auto-ingest | storageAccountResourceId, containerName, ingestion params |
| `IndexedSharePointKnowledgeSource` | SharePoint indexed | resourceId, siteName, containerNames, sensitivityLabels |
| `RemoteSharePointKnowledgeSource` | SharePoint native | resourceId, siteName, containerNames |
| `IndexedOneLakeKnowledgeSource` | Fabric OneLake | oneLakeWorkspaceName, oneLakeItemName, oneLakeItemPath |
| `WebKnowledgeSource` | Bing web search | (no specific params) |

### Knowledge Source Ingestion
- `KnowledgeSourceIngestionParameters` — vectorizer, contentExtractionMode
- `KnowledgeSourceContentExtractionMode` — default | markdown
- `KnowledgeSourceVectorizer` (base) → `KnowledgeSourceAzureOpenAIVectorizer` (resourceUrl, deploymentName, modelName)
- `KnowledgeSourceStatus` — `KnowledgeSourceSynchronizationStatus` (lastUpdated, state)
- `SynchronizationState` — notStarted | running | succeeded | failed
- `KnowledgeSourceStatistics` — documentCount, vectorIndexSize

### Reasoning Effort Details
- `KnowledgeRetrievalReasoningEffortKind` — minimal | low | medium
- `KnowledgeRetrievalMinimalReasoningEffort` — fixed config  
- `KnowledgeRetrievalLowReasoningEffort` — fixed config
- `KnowledgeRetrievalMediumReasoningEffort` — fixed config

---

## Scoring & Relevance

### Scoring Profiles (`ScoringProfile`)
| Property | Type | Notes |
|----------|------|-------|
| `name` | string | Profile name |
| `text` | `TextWeights` | Per-field text boosting weights |
| `functions` | `ScoringFunction[]` | Boost functions |
| `functionAggregation` | `ScoringFunctionAggregation` | How to combine scores |

**`ScoringFunctionAggregation`** — sum | average | minimum | maximum | firstMatching | product

### Scoring Functions
| Type | Description | Parameters |
|------|-------------|------------|
| `MagnitudeScoringFunction` | Boost by numeric value range | boostingRangeStart, boostingRangeEnd, constantBoostBeyondRange |
| `DistanceScoringFunction` | Boost by distance from geo point | referencePointParameter, boostingDistance |
| `FreshnessScoringFunction` | Boost by recency | boostingDuration (ISO 8601) |
| `TagScoringFunction` | Boost by tag match | tagsParameter |

All functions share: fieldName, boost, interpolation (`ScoringFunctionInterpolation`: linear | constant | quadratic | logarithmic)

### Similarity Algorithms
- `BM25SimilarityAlgorithm` — k1 (term frequency saturation), b (field length normalization)
- `ClassicSimilarityAlgorithm` — Lucene TF-IDF (legacy)

---

## Analyzers & Tokenizers

### Custom Analyzer Types
- `CustomAnalyzer` — tokenizer + tokenFilters + charFilters
- `PatternAnalyzer` — regex-based (pattern, flags: `RegexFlags`, lowercase, stopwords)
- `LuceneStandardAnalyzer` — maxTokenLength, stopwords
- `StopAnalyzer` — stopwords list

### Built-in Analyzers (`LexicalAnalyzerName`, 50+ languages)
Language-specific: en.microsoft, en.lucene, de.microsoft, fr.microsoft, es.microsoft, zh-Hans.microsoft, ja.lucene, ko.lucene, ar.microsoft, hi.lucene, etc.
Generic: standard.lucene, standardasciifolding.lucene, simple, keyword, pattern, stop, whitespace

### Tokenizers (`LexicalTokenizerName`, 20+)
| Tokenizer | Description | Key Parameters |
|-----------|-------------|----------------|
| `LuceneStandardTokenizer` / V2 | Unicode text segmentation | maxTokenLength |
| `ClassicTokenizer` | Grammar-based | maxTokenLength |
| `KeywordTokenizer` / V2 | Entire input as one token | maxTokenLength (V2: bufferSize) |
| `NGramTokenizer` | N-gram generation | minGram, maxGram, tokenChars |
| `EdgeNGramTokenizer` | Edge n-grams | minGram, maxGram, tokenChars |
| `PatternTokenizer` | Regex splitting | pattern, flags (`RegexFlags`), group |
| `UaxUrlEmailTokenizer` | URLs/emails preserved | maxTokenLength |
| `PathHierarchyTokenizerV2` | Path segmentation | delimiter, replacement, maxTokenLength, reverse |
| `MicrosoftLanguageTokenizer` | Language-specific | language (`MicrosoftTokenizerLanguage`: 30+ languages) |
| `MicrosoftLanguageStemmingTokenizer` | Language-specific + stemming | language (`MicrosoftStemmingTokenizerLanguage`) |

### Token Filters (35+)
**Stemming:**
- `StemmerTokenFilter` — language (`StemmerTokenFilterLanguage`: 30+ options including porter, snowball variants)
- `StemmerOverrideTokenFilter` — custom stemming rules
- `SnowballTokenFilter` — language (`SnowballTokenFilterLanguage`: 20+ languages)

**Normalization:**
- `AsciiFoldingTokenFilter` — preserveOriginal
- `ElisionTokenFilter` — articles (language-specific article list)
- `CjkBigramTokenFilter` — scripts (`CjkBigramTokenFilterScripts`: han, hiragana, katakana, hangul), ignoreScripts, outputUnigrams

**N-grams & Shingles:**
- `NGramTokenFilter` / V2 — minGram, maxGram
- `EdgeNGramTokenFilter` / V2 — minGram, maxGram, side (front | back)
- `ShingleTokenFilter` — maxShingleSize, minShingleSize, outputUnigrams, outputUnigramsIfNoShingles, tokenSeparator, filterToken

**Stop Words:**
- `StopwordsTokenFilter` — stopwords, stopwordsList (`StopwordsList`: 30+ languages), ignoreCase, removeTrailingStopWords

**Phonetic:**
- `PhoneticTokenFilter` — encoder (`PhoneticEncoder`: metaphone, doubleMetaphone, soundex, refinedSoundex, caverphone1, caverphone2, cologne, nysiis, koelnerPhonetik, haasePhonetik, beiderMorse), replaceOriginalTokens

**Synonyms:**
- `SynonymTokenFilter` — synonyms, ignoreCase, expand

**Length/Truncation:**
- `LengthTokenFilter` — min, max
- `TruncateTokenFilter` — length
- `LimitTokenFilter` — maxTokenCount, consumeAllTokens
- `KeepTokenFilter` — keepWords, keepWordsCase

**Other:**
- `KeywordMarkerTokenFilter` — keywords, ignoreCase
- `PatternCaptureTokenFilter` — patterns, preserveOriginal
- `PatternReplaceTokenFilter` — pattern, replacement
- `CommonGramTokenFilter` — commonWords, ignoreCase, useCommonGramsQuery
- `DictionaryDecompounderTokenFilter` — wordList, minWordSize, minSubwordSize, maxSubwordSize, onlyLongestMatch
- `UniqueTokenFilter` — onlyOnSamePosition

### Character Filters
- `MappingCharFilter` — mappings (list of "x=>y" rules)
- `PatternReplaceCharFilter` — pattern, replacement
- `HtmlStripCharFilter` — remove HTML tags

### Custom Normalizers (`CustomNormalizer`)
- tokenFilters + charFilters (subset: asciifolding, elision, lowercase, uppercase)
- Built-in normalizer names: asciifolding, elision, lowercase, standard, uppercase

**`RegexFlags`** — CANON_EQ | CASE_INSENSITIVE | COMMENTS | DOTALL | LITERAL | MULTILINE | UNICODE_CASE | UNIX_LINES

---

## Aliases & Synonym Maps

| Path | Methods | Operations |
|------|---------|-----------|
| `/aliases` | GET, POST | List/create aliases |
| `/aliases('{name}')` | GET, PUT, DELETE | Get/update/delete alias |
| `/synonymmaps` | GET, POST | List/create synonym maps |
| `/synonymmaps('{name}')` | GET, PUT, DELETE | Get/update/delete synonym map |

- `SearchAlias` — name, indexes (list of index names to route queries to)
- `SynonymMap` — name, format ("solr"), synonyms (rules text), encryptionKey
  - Rule syntax: `"USA, United States => USA"` (explicit mapping), `"USA, United States, America"` (equivalents)

---

## Security & Auth

### Encryption at Rest
- `SearchResourceEncryptionKey` — keyVaultUri, keyVaultKeyName, keyVaultKeyVersion, identity, applicationId
- `AzureActiveDirectoryApplicationCredentials` — applicationId, applicationSecret (service principal for Key Vault access)
- Applied to: indexes, synonym maps, skillsets, knowledge bases, knowledge sources, data sources

### Managed Identity
- `SearchIndexerDataIdentity` (base discriminator)
  - `SearchIndexerDataUserAssignedIdentity` — userAssignedIdentity (ARM resource ID)
  - `SearchIndexerDataNoneIdentity` — use connection string auth

### Document-Level Security
- `PermissionFilter` — mark a field as permission filter (userIds | groupIds | rbacScope)
- `SearchIndexPermissionFilterOption` — enabled | disabled (on index)
- `IndexerPermissionOption` — userIds | groupIds | rbacScope (what indexer ingests)
- `KnowledgeSourceIngestionPermissionOption` — same for KB sources

### API Access
- Admin key — Full CRUD on all resources
- Query key — Read-only (search, suggest, autocomplete, lookup)
- OAuth 2.0 — Azure Entra ID bearer tokens
- `x-ms-query-source-authorization` header — delegated user permissions for document-level security
- `x-ms-enable-elevated-read` header — bypass permission filters

---

## Service Statistics

| Path | Method | Description |
|------|--------|-------------|
| `/servicestats` | GET | Service-level stats |

### `SearchServiceStatistics`
- `counters` — `SearchServiceCounters`: indexesCount, documentsCount, storageSizeInBytes, synonymMapsCount, skillsetsCount, indexersCount, dataSourcesCount, knowledgeBasesCount, knowledgeSourcesCount, vectorIndexSizeInBytes (each as `ResourceCounter` with usage + quota)
- `limits` — `SearchServiceLimits`: maxFieldsPerIndex, maxFieldNestingDepthPerIndex, maxComplexCollectionFieldsPerIndex, maxComplexObjectsInCollectionsPerIndex
- `indexers` — `ServiceIndexersRuntime` (runtime info)

---

## Model Name Enums

### `AzureOpenAIModelName`
text-embedding-ada-002, text-embedding-3-small, text-embedding-3-large, gpt-35-turbo, gpt-35-turbo-16k, gpt-4, gpt-4-32k, gpt-4o, gpt-4o-mini, gpt-4.1, gpt-4.1-mini, gpt-4.1-nano, gpt-5, gpt-5.4-mini

### `AIFoundryModelCatalogName`
OpenAI-CLIP-Image-Text-Embeddings-vit-base-patch32, OpenAI-CLIP-Image-Text-Embeddings-ViT-Large-Patch14-336, Facebook-DinoV2-Image-Embeddings-ViT-Base, Facebook-DinoV2-Image-Embeddings-ViT-Giant, Cohere-embed-v3-english, Cohere-embed-v3-multilingual, Cohere-embed-v4

---

## Quick Enum Reference

| Category | Values |
|----------|--------|
| **Vector Metrics** | cosine, euclidean, dotProduct, hamming |
| **Query Types** | simple, full (Lucene), semantic |
| **Search Mode** | any, all |
| **Index Action** | upload, merge, mergeOrUpload, delete |
| **Indexer Status** | unknown, error, running |
| **Indexer Execution Status** | transientFailure, success, inProgress, reset |
| **Blob Parsing Modes** | default, text, delimitedText, json, jsonArray, jsonLines, markdown |
| **Markdown Submode** | oneToMany, oneToOne |
| **Data Source Types** | azuresql, cosmosdb, azureblob, azuretable, mysql, adlsgen2, onelake, sharepoint |
| **Data To Extract** | storageMetadata, allMetadata, contentAndMetadata |
| **Image Action** | none, generateNormalizedImages, generateNormalizedImagePerPage |
| **Scoring Aggregation** | sum, average, minimum, maximum, firstMatching, product |
| **Interpolation** | linear, constant, quadratic, logarithmic |
| **Vector Filter Mode** | postFilter, preFilter, strictPostFilter |
| **Autocomplete Mode** | oneTerm, twoTerms, oneTermWithContext |
| **Projection Mode** | skipIndexingParentDocuments, includeIndexingParentDocuments |
| **Semantic Error Mode** | partial, fail |
| **Query Debug Mode** | disabled, semantic, vector, queryRewrites, innerHits, all |
| **Chat Response Format** | text, jsonObject, jsonSchema |
| **Reasoning Effort** | minimal, low, medium |
| **Output Mode** | extractiveData, answerSynthesis |
| **KB Source Kind** | searchIndex, azureBlob, indexedSharePoint, remoteSharePoint, indexedOneLake, web |
| **Speller** | none, lexicon |
| **Split Skill Unit** | characters, azureOpenAITokens |
| **Split Skill Tokenizer** | r50k_base, p50k_base, p50k_edit, cl100k_base |