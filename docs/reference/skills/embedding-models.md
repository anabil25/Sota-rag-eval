# Skill: Embedding Models & Vectorizers — Selection, Deployment & Configuration

> For: Retrieve solution accelerator — choosing, deploying, and configuring embedding models for vector search across different architectures.

## When to Use
- Selecting embedding models for Test Mode architecture comparison
- Toggling embedding models in SOTA Eval Mode
- Configuring AI Search integrated vectorization
- Understanding cost/performance tradeoffs

## Model Comparison Table

| Model | Provider | Dimensions | MTEB Avg | Context Length | Cost / 1M tokens | Latency (p50) | Notes |
|---|---|---|---|---|---|---|---|
| text-embedding-3-small | Azure OpenAI | 1536 | 62.3 | 8191 | $0.02 | ~12ms | Cheapest Azure-native. Good baseline. |
| text-embedding-3-large | Azure OpenAI | 3072 | 64.6 | 8191 | $0.13 | ~18ms | Higher fidelity. Default for most use cases. |
| text-embedding-ada-002 | Azure OpenAI | 1536 | 61.0 | 8191 | $0.10 | ~15ms | Legacy. text-embedding-3-small is cheaper and better. |
| BGE-M3 | Foundry managed compute | 1024 | 66.1 | 8192 | Managed compute | ~25ms | Dense + sparse + multi-vector in one pass. Deploy via Foundry. |
| Cohere embed-v3-english | AI Foundry Catalog | 1024 | 64.5 | 512 | $0.10 | ~15ms | Strong English. Available in Foundry model catalog. |
| Cohere embed-v3-multilingual | AI Foundry Catalog | 1024 | 64.3 | 512 | $0.10 | ~18ms | 100+ languages. |
| Cohere embed-v4 | AI Foundry Catalog | 1024 | — | 512 | TBD | TBD | Latest Cohere. Preview in Foundry. |

## Azure OpenAI Model Deployment

### Bicep
```bicep
resource aiServicesAccount 'Microsoft.CognitiveServices/accounts@2024-10-01' = {
  name: aiServicesName
  location: location
  kind: 'AIServices'
  sku: { name: 'S0' }
  identity: { type: 'SystemAssigned' }
  properties: {
    customSubDomainName: aiServicesName
    publicNetworkAccess: 'Enabled'
  }
}

resource embeddingDeployment 'Microsoft.CognitiveServices/accounts/deployments@2024-10-01' = {
  parent: aiServicesAccount
  name: 'text-embedding-3-large'
  sku: {
    name: 'Standard'
    capacity: 120  // TPM in thousands (120K TPM)
  }
  properties: {
    model: {
      format: 'OpenAI'
      name: 'text-embedding-3-large'
      version: '1'  // check latest with az cognitiveservices model list
    }
  }
}
```

### Python SDK — Generate Embeddings
```python
from openai import AzureOpenAI
from azure.identity import DefaultAzureCredential, get_bearer_token_provider

token_provider = get_bearer_token_provider(
    DefaultAzureCredential(),
    "https://cognitiveservices.azure.com/.default"
)

client = AzureOpenAI(
    azure_endpoint=f"https://{ai_services_name}.openai.azure.com/",
    azure_ad_token_provider=token_provider,
    api_version="2024-10-21"
)

response = client.embeddings.create(
    input=["What are the confidentiality rules for DPA?"],
    model="text-embedding-3-large"
)
vector = response.data[0].embedding  # list of 3072 floats
```

## AI Search Integrated Vectorization

### Index Vectorizer (query-time automatic embedding)
```python
from azure.search.documents.indexes.models import (
    AzureOpenAIVectorizer,
    AzureOpenAIVectorizerParameters,
    VectorSearch,
    VectorSearchProfile,
    HnswAlgorithmConfiguration,
)

vector_search = VectorSearch(
    algorithms=[HnswAlgorithmConfiguration(name="hnsw-config")],
    profiles=[
        VectorSearchProfile(
            name="vector-profile",
            algorithm_configuration_name="hnsw-config",
            vectorizer_name="openai-vectorizer"
        )
    ],
    vectorizers=[
        AzureOpenAIVectorizer(
            vectorizer_name="openai-vectorizer",
            parameters=AzureOpenAIVectorizerParameters(
                resource_url=f"https://{ai_services_name}.openai.azure.com",
                deployment_name="text-embedding-3-large",
                model_name="text-embedding-3-large"
            )
        )
    ]
)
```

### Skillset Embedding (indexing-time automatic embedding)
```python
from azure.search.documents.indexes.models import (
    AzureOpenAIEmbeddingSkill,
    InputFieldMappingEntry,
    OutputFieldMappingEntry,
)

embedding_skill = AzureOpenAIEmbeddingSkill(
    name="embed-content",
    description="Generate embeddings for content chunks",
    resource_url=f"https://{ai_services_name}.openai.azure.com",
    deployment_name="text-embedding-3-large",
    model_name="text-embedding-3-large",
    inputs=[InputFieldMappingEntry(name="text", source="/document/content")],
    outputs=[OutputFieldMappingEntry(name="embedding", target_name="content_vector")]
)
```

## Foundry Model Catalog (Cohere, etc.)

Models deployed via the AI Foundry Model Catalog use a different endpoint format:

```python
# Cohere via Foundry — uses AML-style endpoint, not OpenAI SDK
from azure.search.documents.indexes.models import (
    AzureOpenAIVectorizer,  # same vectorizer type, different params
    AzureOpenAIVectorizerParameters,
)

# For Foundry catalog models, the endpoint is the model's inference URL
# and the API key is the Foundry key
```

For AI Search, Foundry catalog models can be used via:
1. `AIFoundryModelCatalogName` in the index vectorizer config (preview API)
2. AML custom skill pointing at the Foundry endpoint
3. Web API vectorizer (`customWebApi`) wrapping the Foundry REST call

## BGE-M3 (via Foundry Managed Compute)

BGE-M3 produces dense, sparse, and ColBERT multi-vector embeddings in one pass. Deploy it through **Foundry managed compute** — no self-hosting, no ACI, no AKS.

### Deployment via Foundry
```bash
# Deploy BGE-M3 to a managed compute endpoint via Foundry
az ml online-endpoint create --name bgem3-endpoint --resource-group <rg> --workspace-name <foundry-project>
az ml online-deployment create --name bgem3 --endpoint-name bgem3-endpoint \\
  --model BAAI/bge-m3 --instance-type Standard_NC6s_v3 \\
  --resource-group <rg> --workspace-name <foundry-project>
```

Foundry manages the VMs, scaling, health probes, and auth. You get a REST endpoint with managed identity support.

### AML Vectorizer for BGE-M3 in AI Search
```python
from azure.search.documents.indexes.models import (
    AMLVectorizer,
    AMLParameters,
)

bgem3_vectorizer = AMLVectorizer(
    vectorizer_name="bgem3-vectorizer",
    aml_parameters=AMLParameters(
        resource_id="<foundry-endpoint-resource-id>",  # managed identity auth
        model_name="bge-m3"
    )
)
```

### AML Skill for BGE-M3 at Index Time
```json
{
  "@odata.type": "#Microsoft.Skills.Custom.AmlSkill",
  "resourceId": "<foundry-endpoint-resource-id>",
  "region": "eastus2",
  "timeout": "PT60S"
}
```

## SOTA Eval Mode — Embedding Toggle Matrix

| Toggle Variant | Model | Dimensions | Expected Impact |
|---|---|---|---|
| Default | text-embedding-3-large | 3072 | Baseline |
| Cheaper | text-embedding-3-small | 1536 | Lower cost, ~2-3% lower accuracy |
| Multi-vector | BGE-M3 (Foundry managed compute) | 1024 dense + sparse | Higher accuracy for keyword+semantic, adds managed compute cost |
| Foundry Cohere | Cohere embed-v4 | 1024 | Different embedding space, may help domain-specific |

## Key Gotchas

1. **Dimension mismatch kills queries** — The index vector field dimensions MUST match the model output dimensions. Changing models means rebuilding the index.
2. **text-embedding-3 supports dimension reduction** — You can request `dimensions=1024` from text-embedding-3-large to reduce storage while keeping most of the quality.
3. **Deployment quota != unlimited** — Each region has TPM limits. For bulk indexing (embedding 300 docs), you may hit rate limits. Use retry with backoff.
4. **Vectorizer ≠ embedding skill** — The vectorizer runs at query time (embeds the user's query). The embedding skill runs at index time (embeds documents). Both must use the same model.
5. **BGE-M3 sparse embeddings** — AI Search supports sparse vector fields, but the format must match the Lucene sparse format. May need a custom skill to transform BGE-M3 sparse output.
