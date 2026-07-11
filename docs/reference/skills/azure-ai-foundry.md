# Skill: Microsoft Foundry — Model Deployment, Hosting & AI Search Integration

> For: Retrieve solution accelerator — deploying embedding models and LLMs, connecting them to AI Search, and calling them from Python.
>
> **Branding (March 2026):** "Azure AI Foundry" is now **"Microsoft Foundry"**. The old "Azure AI Studio" → "Azure AI Foundry" → now just "Foundry." The resource type (`Microsoft.CognitiveServices/accounts`) is unchanged.

## What Foundry IS (2026)

Foundry is the **unified PaaS for all AI model operations** — NOT just Azure OpenAI rebranded. It consolidates:

| Previous Concept | Foundry Equivalent |
|---|---|
| Azure OpenAI Service | Foundry resource with OpenAI model deployments |
| Azure AI Services (multi-service) | Foundry Tools |
| Azure ML managed endpoints | Foundry managed compute (classic) |
| Separate SDKs (azure-ai-inference, azure-ai-ml) | `azure-ai-projects` v2.x + OpenAI SDK |

A **Foundry resource** is the recommended starting point. It's a superset — includes Azure OpenAI PLUS the full model catalog, agents, evaluations, and Foundry Tools. An Azure OpenAI resource can be upgraded to a Foundry resource in-place.

## Three Model Hosting Paths

| Path | Resource Required | What You Deploy | Billing | AI Search Integration |
|---|---|---|---|---|
| **Standard deployment** (new Foundry) | Foundry resource (`kind: AIServices`) | Azure OpenAI models + select partners | Pay-per-token or PTU | `AzureOpenAIVectorizer` + `AzureOpenAIEmbeddingSkill` |
| **Serverless API** (classic Hub only) | Hub-based project (`Microsoft.MachineLearningServices`) | Partner models (Cohere, Mistral, Meta, etc.) | Pay-per-token via Marketplace | `AMLVectorizer` + `AMLSkill` |
| **Managed compute** (classic Hub only) | Hub-based project + VM quota | HuggingFace / custom models on dedicated VMs | VM compute hours | `AMLSkill` + `AMLVectorizer` (via `resourceId`) |

### Which Path for Which Model?

```
I need an embedding model for AI Search →
  ├─ text-embedding-3-small / 3-large / ada-002
  │    → Standard deployment (Foundry resource)
  │    → AzureOpenAIEmbeddingSkill + AzureOpenAIVectorizer
  │    → Zero compute management, pay-per-token
  │    → ⭐ RECOMMENDED DEFAULT
  │
  ├─ Cohere embed-v3 / embed-v4
  │    → Serverless API (classic Hub)
  │    → AMLSkill + AMLVectorizer (kind: "aml", modelName from catalog enum)
  │    → Zero compute, pay-per-token via Marketplace
  │
  ├─ BGE-M3 / custom HuggingFace model
  │    → Managed compute (classic Hub) — deploys to dedicated VMs
  │    → AMLSkill + AMLVectorizer (via resourceId, token auth)
  │    → You pay for VM uptime
  │    → OR: use Container Apps / AKS + CustomWebApiSkill + CustomWebApiVectorizer
  │
  └─ Don't know → use text-embedding-3-large (best default)
```

## CRITICAL: Deployment Order
**Foundry resources MUST be created BEFORE AI Search** if Search uses integrated vectorization. The vectorizer/skill config references the OpenAI endpoint + deployment name — these must exist at index creation time. See `azure-bicep-iac.md` deployment order.

---

## End-to-End Walkthrough: Foundry Embedding → AI Search (Path 1 — Azure OpenAI)

This is the complete sequence. Every step produces a value consumed by the next step.

### Step 1: Deploy Foundry resource + embedding model (Bicep)
```bicep
resource aiFoundry 'Microsoft.CognitiveServices/accounts@2025-04-01-preview' = {
  name: 'akpolicy-foundry'               // ← this becomes {foundry-resource}
  location: 'eastus2'
  kind: 'AIServices'
  sku: { name: 'S0' }
  identity: { type: 'SystemAssigned' }
  properties: { customSubDomainName: 'akpolicy-foundry' }
}

resource embeddingDeploy 'Microsoft.CognitiveServices/accounts/deployments@2025-04-01-preview' = {
  parent: aiFoundry
  name: 'text-embedding-3-large'          // ← this becomes {deployment-name}
  sku: { name: 'GlobalStandard', capacity: 120 }
  properties: {
    model: { format: 'OpenAI', name: 'text-embedding-3-large', version: '1' }
  }
}
```
**Outputs needed downstream:**
- `resourceUri` = `https://akpolicy-foundry.openai.azure.com`
- `deploymentId` = `text-embedding-3-large`
- `modelName` = `text-embedding-3-large`
- `dimensions` = `3072`

### Step 2: Deploy AI Search + grant role (Bicep)
```bicep
resource searchService 'Microsoft.Search/searchServices@2023-11-01' = {
  name: 'akpolicy-search'
  location: 'eastus2'
  sku: { name: 'basic' }
  identity: { type: 'SystemAssigned' }
}

// Grant Search → Foundry: Cognitive Services OpenAI User
resource searchOpenAIRole 'Microsoft.Authorization/roleAssignments@2022-04-01' = {
  name: guid(aiFoundry.id, searchService.id, '5e0bd9bd-7b93-4f28-af87-19fc36ad61bd')
  scope: aiFoundry
  properties: {
    roleDefinitionId: subscriptionResourceId('Microsoft.Authorization/roleDefinitions', '5e0bd9bd-7b93-4f28-af87-19fc36ad61bd')
    principalId: searchService.identity.principalId
    principalType: 'ServicePrincipal'
  }
}
```
⏳ **Wait ~60 seconds** after role assignment for Azure AD propagation before creating the index.

### Step 3: Create index with vector field + vectorizer (Python SDK)
```python
from azure.search.documents.indexes import SearchIndexClient
from azure.search.documents.indexes.models import (
    SearchIndex, SearchField, SearchFieldDataType,
    VectorSearch, VectorSearchProfile, HnswAlgorithmConfiguration,
    AzureOpenAIVectorizer, AzureOpenAIVectorizerParameters, SemanticConfiguration,
    SemanticPrioritizedFields, SemanticField
)
from azure.identity import DefaultAzureCredential

index_client = SearchIndexClient(
    endpoint="https://akpolicy-search.search.windows.net",
    credential=DefaultAzureCredential()
)

index = SearchIndex(
    name="policies-index",
    fields=[
        SearchField(name="id", type=SearchFieldDataType.String, key=True,
                    analyzer_name="keyword"),       # ← REQUIRED when using index projections
        SearchField(name="parent_id", type=SearchFieldDataType.String, filterable=True),  # ← REQUIRED for projections
        SearchField(name="content", type=SearchFieldDataType.String, searchable=True),
        SearchField(name="title", type=SearchFieldDataType.String, searchable=True, filterable=True),
        SearchField(name="policy_id", type=SearchFieldDataType.String, filterable=True, facetable=True),
        SearchField(
            name="content_vector",
            type=SearchFieldDataType.Collection(SearchFieldDataType.Single),
            searchable=True,
            vector_search_dimensions=3072,          # ← must match model output
            vector_search_profile_name="vector-profile"
        ),
    ],
    vector_search=VectorSearch(
        algorithms=[HnswAlgorithmConfiguration(name="hnsw-config")],
        profiles=[
            VectorSearchProfile(
                name="vector-profile",
                algorithm_configuration_name="hnsw-config",
                vectorizer_name="openai-vectorizer"   # ← links to vectorizer below
            )
        ],
        vectorizers=[
            AzureOpenAIVectorizer(
                vectorizer_name="openai-vectorizer",
                parameters=AzureOpenAIVectorizerParameters(
                    resource_url="https://akpolicy-foundry.openai.azure.com",  # ← from Step 1
                    deployment_name="text-embedding-3-large",                   # ← from Step 1
                    model_name="text-embedding-3-large"                         # ← from Step 1
                )
            )
        ]
    ),
)
index_client.create_or_update_index(index)
```

### Step 4: Create skillset with embedding skill + index projections (Python SDK)

> **CRITICAL:** The index (Step 3) MUST be created before the skillset because index
> projections reference the target index by name. If the index doesn't exist, skillset
> creation will fail.

```python
from azure.search.documents.indexes.models import (
    SearchIndexerSkillset, AzureOpenAIEmbeddingSkill,
    SplitSkill, InputFieldMappingEntry, OutputFieldMappingEntry,
    SearchIndexerIndexProjection, SearchIndexerIndexProjectionSelector,
    SearchIndexerIndexProjectionsParameters
)

skillset = SearchIndexerSkillset(
    name="policies-skillset",
    skills=[
        SplitSkill(
            name="chunk",
            text_split_mode="pages",
            maximum_page_length=2000,
            page_overlap_length=500,
            inputs=[InputFieldMappingEntry(name="text", source="/document/content")],
            outputs=[OutputFieldMappingEntry(name="textItems", target_name="chunks")]
        ),
        AzureOpenAIEmbeddingSkill(
            name="embed",
            context="/document/chunks/*",                                    # ← REQUIRED: iterate over each chunk
            resource_url="https://akpolicy-foundry.openai.azure.com",       # ← same as vectorizer
            deployment_name="text-embedding-3-large",                        # ← same as vectorizer
            model_name="text-embedding-3-large",                             # ← same as vectorizer
            dimensions=3072,                                                  # ← same as index field
            inputs=[InputFieldMappingEntry(name="text", source="/document/chunks/*")],
            outputs=[OutputFieldMappingEntry(name="embedding", target_name="content_vector")]
        ),
    ],
    # Index projections map each chunk to a separate index document.
    # Do NOT use output_field_mappings on the indexer — it causes Edm.Double vs
    # Edm.Single type mismatches with vector fields.
    index_projection=SearchIndexerIndexProjection(               # ← singular, NOT index_projections
        selectors=[
            SearchIndexerIndexProjectionSelector(
                target_index_name="policies-index",              # ← must match Step 3 index name
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
            projection_mode="skipIndexingParentDocuments",
        ),
    ),
)
indexer_client.create_or_update_skillset(skillset)
```

### Step 5: Create data source + indexer → run (Python SDK)
```python
from azure.search.documents.indexes.models import (
    SearchIndexerDataSourceConnection, SearchIndexerDataContainer, SearchIndexer
)

# Data source (blob, managed identity)
data_source = SearchIndexerDataSourceConnection(
    name="policies-blob",
    type="azureblob",
    connection_string=f"ResourceId={storage_resource_id};",
    container=SearchIndexerDataContainer(name="policies")
)
indexer_client.create_or_update_data_source_connection(data_source)

# Indexer — NO field_mappings or output_field_mappings needed.
# Index projections (set on the skillset in Step 4) handle all chunk-to-document mapping.
indexer = SearchIndexer(
    name="policies-indexer",
    data_source_name="policies-blob",
    target_index_name="policies-index",
    skillset_name="policies-skillset",
    parameters={"configuration": {
        "parsingMode": "markdown",
        "markdownParsingSubmode": "oneToMany",
        "dataToExtract": "contentAndMetadata",
    }}
)
indexer_client.create_or_update_indexer(indexer)
# Indexer runs automatically. Check status:
# indexer_client.get_indexer_status("policies-indexer")
```

**Creation order matters:** data source → index (Step 3) → skillset with projections (Step 4) → indexer (Step 5). The index must exist before the skillset because projections reference it by name.

**That's the complete path: Foundry deployment → role assignment → index with vectorizer → skillset with embedding skill + projections → data source → indexer. All values flow from Step 1 through Step 5.**

---

## Resource Model (Bicep)

### Foundry Resource + Project
```bicep
resource aiFoundry 'Microsoft.CognitiveServices/accounts@2025-04-01-preview' = {
  name: foundryName
  location: location
  kind: 'AIServices'
  sku: { name: 'S0' }
  identity: { type: 'SystemAssigned' }
  properties: {
    customSubDomainName: foundryName
    publicNetworkAccess: 'Enabled'
  }
}

// Optional: Project for team boundaries
resource project 'Microsoft.CognitiveServices/accounts/projects@2025-04-01-preview' = {
  parent: aiFoundry
  name: 'retrieve-eval'
  location: location
  properties: {}
}
```

### Model Deployment (Standard)
```bicep
resource embeddingDeploy 'Microsoft.CognitiveServices/accounts/deployments@2025-04-01-preview' = {
  parent: aiFoundry
  name: 'text-embedding-3-large'
  sku: {
    name: 'GlobalStandard'
    capacity: 120  // TPM in thousands
  }
  properties: {
    model: {
      format: 'OpenAI'
      name: 'text-embedding-3-large'
      version: '1'
    }
  }
}

resource llmDeploy 'Microsoft.CognitiveServices/accounts/deployments@2025-04-01-preview' = {
  parent: aiFoundry
  name: 'gpt-41'
  sku: {
    name: 'GlobalStandard'
    capacity: 80
  }
  properties: {
    model: {
      format: 'OpenAI'
      name: 'gpt-4.1'
      version: '2025-04-14'
    }
  }
  dependsOn: [embeddingDeploy]  // sequential deployment required
}
```

**IMPORTANT**: Model deployments under the same account must be deployed **sequentially**. Use `dependsOn` to chain them.

### Non-OpenAI Model Deployment (e.g., Phi-4, DeepSeek)
```bash
az cognitiveservices account deployment create \
  --name $foundryName --resource-group $rg \
  --deployment-name Phi-4-mini-instruct \
  --model-name Phi-4-mini-instruct \
  --model-version 1 \
  --model-format Microsoft \
  --sku-capacity 1 \
  --sku-name GlobalStandard
```

---

## Deployment SKU Types

| SKU | Data Zone | Billing | Use Case |
|---|---|---|---|
| `GlobalStandard` | Any Azure region | Pay-per-token | **Recommended default** — highest quota, best availability |
| `Standard` | Single region | Pay-per-token | Regional compliance |
| `DataZoneStandard` | US or EU zone | Pay-per-token | EU/US data residency |
| `GlobalProvisionedManaged` | Any Azure region | Reserved PTU | Predictable high throughput |
| `ProvisionedManaged` | Single region | Reserved PTU | Regional + throughput |

---

## Available Models

### Embedding Models (for AI Search vectorization)
| Model | Dimensions | MTEB Avg | Max Tokens | Cost / 1M tokens |
|---|---|---|---|---|
| `text-embedding-3-large` | 3072 (configurable) | 64.6 | 8,191 | $0.13 |
| `text-embedding-3-small` | 1536 (configurable) | 62.3 | 8,191 | $0.02 |
| `text-embedding-ada-002` | 1536 (fixed) | 61.0 | 8,191 | $0.10 |
| Cohere embed-v4 (serverless) | 256-1536 | — | 512 | ~$0.10 |
| Cohere embed-v3-multilingual (serverless) | 1024 | 64.3 | 512 | ~$0.10 |

### Chat/LLM Models (for eval generation, failure classification, agentic KB)
| Model | Context | Notes |
|---|---|---|
| `gpt-4.1` | 1M tokens | Long-context, recommended for eval |
| `gpt-4.1-mini` | 1M tokens | Cost-efficient eval |
| `gpt-4.1-nano` | 1M tokens | Cheapest classification |
| `gpt-5` | 400K tokens | Latest GA |
| `gpt-5.4-mini` | 400K tokens | Latest, cost-efficient |

---

## Endpoints

| Deployment Type | Format |
|---|---|
| Standard (OpenAI) | `https://<foundry-resource>.openai.azure.com/` |
| Foundry Models inference | `https://<foundry-resource>.services.ai.azure.com/models` |
| Project endpoint | `https://<foundry-resource>.services.ai.azure.com/api/projects/<project>` |
| Serverless API (classic) | `https://<deployment-id>.<region>.models.ai.azure.com` |
| Managed compute (classic) | `https://<endpoint>.<region>.inference.ml.azure.com/score` |

---

## Python SDK

### Packages
```
pip install openai azure-identity azure-ai-projects
```

`azure-ai-inference` is **DEPRECATED** (retiring May 2026). Use the OpenAI SDK for inference.

### Client Initialization
```python
from openai import AzureOpenAI
from azure.identity import DefaultAzureCredential, get_bearer_token_provider

token_provider = get_bearer_token_provider(
    DefaultAzureCredential(),
    "https://cognitiveservices.azure.com/.default"
)
client = AzureOpenAI(
    azure_endpoint=f"https://{foundry_name}.openai.azure.com/",
    azure_ad_token_provider=token_provider,
    api_version="2024-10-21"
)
```

### Embeddings
```python
response = client.embeddings.create(
    model="text-embedding-3-large",
    input=["How do I apply for SNAP benefits?"]
)
vector = response.data[0].embedding  # list of 3072 floats
```

### Chat Completions
```python
response = client.chat.completions.create(
    model="gpt-4.1",
    messages=[
        {"role": "system", "content": "Generate evaluation questions."},
        {"role": "user", "content": "Based on this policy text, generate 5 questions..."}
    ],
    temperature=0.7
)
```

### Via azure-ai-projects (Foundry-native)
```python
from azure.ai.projects import AIProjectClient
from azure.identity import DefaultAzureCredential

project = AIProjectClient(
    endpoint="https://<resource>.services.ai.azure.com/api/projects/<project>",
    credential=DefaultAzureCredential()
)

# List available deployments
for d in project.deployments.list():
    print(d.name, d.model_name, d.sku)

# Get OpenAI client pre-configured for this project
with project.get_openai_client() as openai_client:
    response = openai_client.embeddings.create(
        model="text-embedding-3-large",
        input=["test"]
    )
```

---

## AI Search Integration — All 4 Vectorizer Paths

| AI Search Vectorizer Kind | AI Search Skill | Targets | Auth |
|---|---|---|---|
| `azureOpenAI` | `AzureOpenAIEmbeddingSkill` | Standard Foundry deployments (text-embedding-3-*) | API key or managed identity |
| `aml` | `AmlSkill` | Serverless catalog deployments (Cohere) or managed compute endpoints | Key or managed identity via `resourceId` |
| `aiServicesVision` | `VisionVectorizeSkill` | Azure Vision multimodal embeddings | API key or managed identity |
| `customWebApi` | `WebApiSkill` | Any HTTP endpoint (self-hosted models, Functions, etc.) | Custom headers |

### Path 1: AzureOpenAI (standard deployment — recommended)
```json
// Skillset (index time)
{
  "@odata.type": "#Microsoft.Skills.Text.AzureOpenAIEmbeddingSkill",
  "resourceUri": "https://{foundry-resource}.openai.azure.com",
  "deploymentId": "text-embedding-3-large",
  "modelName": "text-embedding-3-large",
  "dimensions": 3072
}

// Vectorizer (query time)
{
  "name": "openai-vectorizer",
  "kind": "azureOpenAI",
  "azureOpenAIParameters": {
    "resourceUri": "https://{foundry-resource}.openai.azure.com",
    "deploymentId": "text-embedding-3-large",
    "modelName": "text-embedding-3-large"
  }
}
```

### Path 2: AML / Foundry Catalog (serverless — Cohere)
```json
// Vectorizer (query time)
{
  "name": "cohere-vectorizer",
  "kind": "aml",
  "amlParameters": {
    "uri": "https://Cohere-embed-v3-multilingual.eastus.models.ai.azure.com",
    "key": "{deployment-key}",
    "modelName": "Cohere-embed-v3-multilingual"
  }
}
```

Supported `modelName` values from the `AIFoundryModelCatalogName` enum:
- `Cohere-embed-v3-english`
- `Cohere-embed-v3-multilingual`
- `Cohere-embed-v4`
- `OpenAI-CLIP-Image-Text-Embeddings-*` (multimodal)
- `Facebook-DinoV2-Image-Embeddings-*` (image only)

### Path 3: Managed compute (classic — custom models)
```json
// Skill (index time)
{
  "@odata.type": "#Microsoft.Skills.Custom.AmlSkill",
  "resourceId": "subscriptions/{sub}/resourceGroups/{rg}/providers/Microsoft.MachineLearningServices/workspaces/{ws}/onlineendpoints/{endpoint}",
  "region": "eastus",
  "inputs": [...],
  "outputs": [...]
}
```

### Both skill and vectorizer MUST use the same model and dimensions.

---

## Auth: Search → Foundry

| Method | How | Notes |
|---|---|---|
| API Key | Add `"apiKey": "{key}"` to skill/vectorizer config | Simple, works everywhere |
| System managed identity | Assign `Cognitive Services OpenAI User` to Search's identity on Foundry | Recommended, keyless |
| Keyless billing (preview) | `AIServicesByIdentity` in skillset cognitiveServices block | No region restriction |

---

## Attaching Foundry for Built-in Skill Billing

Built-in skills (OCR, Entity Recognition, etc.) need a Foundry resource for billing after 20 free calls/indexer/day:

```json
// Keyless (preview, recommended)
"cognitiveServices": {
  "@odata.type": "#Microsoft.Azure.Search.AIServicesByIdentity",
  "subdomainUrl": "https://{foundry-resource}.services.ai.azure.com"
}

// Key-based (GA)
"cognitiveServices": {
  "@odata.type": "#Microsoft.Azure.Search.AIServicesByKey",
  "key": "{key}",
  "subdomainUrl": "https://{foundry-resource}.services.ai.azure.com"
}
```

---

## RBAC Roles
| Role | GUID | Assigned To → Resource | Purpose |
|---|---|---|---|
| Cognitive Services OpenAI User | `5e0bd9bd-7b93-4f28-af87-19fc36ad61bd` | AI Search → Foundry | Call embeddings/completions |
| Cognitive Services User | `a97b65f3-24c7-4388-baec-2e87135dc908` | AI Search → Foundry | Broader: all cognitive services |

---

## Key Gotchas

1. **Foundry before Search in Bicep** — vectorizer/skill references must resolve at index creation time. Deploy Foundry + model deployment BEFORE the Search index.
2. **Sequential model deployments** — under the same Foundry account, deployments must be chained with `dependsOn`. Parallel deployments fail.
3. **`azure-ai-inference` is deprecated** — use `openai` SDK or `azure-ai-projects` v2.x. Retiring May 2026.
4. **Serverless API and Managed Compute are classic-only** — require Hub-based projects (`Microsoft.MachineLearningServices/workspaces`), NOT the new Foundry resource. If you need Cohere embedding or BGE-M3 via managed compute, you need the classic infrastructure.
5. **BGE-M3 is NOT in the Foundry model catalog for standard deployment** — if you specifically need BGE-M3, use managed compute (classic) or Container Apps + CustomWebApi. For most use cases, `text-embedding-3-large` is the simpler path.
6. **Dimension reduction** — `text-embedding-3-large` supports `dimensions` parameter. Request `dimensions=1024` to halve storage with minimal quality loss. Both skill AND vectorizer must specify the same value.
7. **Role assignment propagation** — after granting `Cognitive Services OpenAI User`, wait ~30-60 seconds. Bicep `dependsOn` doesn't help — it's Azure AD propagation.
