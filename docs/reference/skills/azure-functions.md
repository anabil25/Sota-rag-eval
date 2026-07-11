# Skill: Azure Functions — GraphRAG/LightRAG Query API & Custom Orchestration

> For: Retrieve solution accelerator — deploying serverless functions as query endpoints for GraphRAG/LightRAG, and as custom orchestrators ONLY when native capabilities are insufficient.

## IMPORTANT: When NOT to Use Functions

The following scenarios are handled **natively** by Azure AI Search — do NOT use Functions for these:

| Scenario | Native Alternative | See |
|---|---|---|
| Multi-hop agentic retrieval | **Knowledge Bases API** with `reasoningEffort: "medium"` — built-in query planning, iterative search, answer synthesis | `azure-ai-search-agentic.md` |
| Thin query API for Copilot Studio | Call AI Search `docs/search.post.search` or KB `/retrieve` endpoint directly via HTTP action | `azure-ai-search.md` |
| Query expansion / rewriting | Built-in `queryRewrites: "generative"` parameter (semantic query type) | `azure-ai-search.md` |
| Extractive answers / captions | Built-in `answers` and `captions` query parameters | `azure-ai-search.md` |
| LLM enrichment at index time | **ChatCompletionSkill** in the indexer skillset | `azure-indexer-pipeline.md` |

## When to ACTUALLY Use Functions
- **GraphRAG architecture**: query endpoint wrapping `graphrag.query` against Cosmos DB — no native equivalent
- **LightRAG architecture**: query endpoint wrapping `lightrag.query` — no native equivalent
- **Custom orchestration logic**: business-logic gating, external API calls mid-retrieval, custom scoring that the KB reasoning modes can't express

## Resource Types
| Resource | Type | Purpose |
|---|---|---|
| App Service Plan | `Microsoft.Web/serverfarms` | Hosting plan (Consumption or Flex Consumption) |
| Function App | `Microsoft.Web/sites` | The function app itself |
| Storage Account | `Microsoft.Storage/storageAccounts` | Required by Functions runtime |

## Bicep

### Function App (Python, Flex Consumption)
```bicep
resource functionPlan 'Microsoft.Web/serverfarms@2023-12-01' = {
  name: '${namePrefix}-plan'
  location: location
  kind: 'functionapp'
  sku: {
    tier: 'FlexConsumption'
    name: 'FC1'
  }
  properties: {
    reserved: true  // Linux
  }
}

resource functionApp 'Microsoft.Web/sites@2023-12-01' = {
  name: '${namePrefix}-func'
  location: location
  kind: 'functionapp,linux'
  identity: { type: 'SystemAssigned' }
  properties: {
    serverFarmId: functionPlan.id
    siteConfig: {
      linuxFxVersion: 'PYTHON|3.11'
      appSettings: [
        { name: 'AzureWebJobsStorage__accountName', value: funcStorageAccount.name }
        { name: 'FUNCTIONS_EXTENSION_VERSION', value: '~4' }
        { name: 'FUNCTIONS_WORKER_RUNTIME', value: 'python' }
        { name: 'SEARCH_ENDPOINT', value: 'https://${searchName}.search.windows.net' }
        { name: 'SEARCH_INDEX_NAME', value: 'policies-index' }
      ]
    }
  }
}
```

### Role Assignments for Function App
```bicep
// Function → AI Search: Search Index Data Reader
var searchIndexDataReaderRoleId = '1407120a-92aa-4202-b7e9-c0e197c71c8f'

resource funcSearchReader 'Microsoft.Authorization/roleAssignments@2022-04-01' = {
  name: guid(searchService.id, functionApp.id, searchIndexDataReaderRoleId)
  scope: searchService
  properties: {
    roleDefinitionId: subscriptionResourceId('Microsoft.Authorization/roleDefinitions', searchIndexDataReaderRoleId)
    principalId: functionApp.identity.principalId
    principalType: 'ServicePrincipal'
  }
}

// Function → Cosmos DB: Data Contributor (for GraphRAG)
// See azure-cosmos-db.md for Cosmos role assignment pattern

// Function → Azure OpenAI: Cognitive Services OpenAI User
var cogServicesOpenAIUserRoleId = '5e0bd9bd-7b93-4f28-af87-19fc36ad61bd'
```

## Function Patterns

### Pattern 1: Thin Query API (keyword/hybrid/vector)
```python
# function_app.py
import azure.functions as func
from azure.identity import DefaultAzureCredential
from azure.search.documents import SearchClient

app = func.FunctionApp()
credential = DefaultAzureCredential()

@app.function_name(name="search")
@app.route(route="search", methods=["POST"])
async def search(req: func.HttpRequest) -> func.HttpResponse:
    body = req.get_json()
    query = body["query"]
    top_k = body.get("top_k", 10)
    
    client = SearchClient(
        endpoint=os.environ["SEARCH_ENDPOINT"],
        index_name=os.environ["SEARCH_INDEX_NAME"],
        credential=credential
    )
    
    results = client.search(
        search_text=query,
        query_type="semantic",
        semantic_configuration_name="default",
        top=top_k,
        select=["policy_id", "title", "content"]
    )
    
    docs = [{"policy_id": r["policy_id"], "title": r["title"], 
             "content": r["content"], "score": r["@search.score"]}
            for r in results]
    
    return func.HttpResponse(json.dumps({"results": docs}), mimetype="application/json")
```

### Pattern 2: Agentic Multi-Hop Orchestrator
```python
@app.function_name(name="agentic_search")
@app.route(route="agentic-search", methods=["POST"])
async def agentic_search(req: func.HttpRequest) -> func.HttpResponse:
    body = req.get_json()
    query = body["query"]
    
    # Step 1: Initial retrieval
    initial_results = search_index(query, top_k=20)
    
    # Step 2: LLM decides if more info needed
    analysis = await analyze_results(query, initial_results)
    
    if analysis["needs_more_info"]:
        # Step 3: Generate follow-up queries from LLM
        followup_queries = analysis["followup_queries"]
        
        # Step 4: Run follow-up searches
        for fq in followup_queries:
            more_results = search_index(fq, top_k=10)
            initial_results.extend(more_results)
    
    # Step 5: Deduplicate and re-rank
    final_results = deduplicate_and_rank(initial_results)
    
    return func.HttpResponse(json.dumps({"results": final_results}))
```

### Pattern 3: GraphRAG Query Endpoint
```python
@app.function_name(name="graphrag_search")
@app.route(route="graphrag-search", methods=["POST"])
async def graphrag_search(req: func.HttpRequest) -> func.HttpResponse:
    body = req.get_json()
    query = body["query"]
    mode = body.get("mode", "local")  # "local" or "global"
    
    if mode == "global":
        result = graphrag_global_search(query)
    else:
        result = graphrag_local_search(query)
    
    return func.HttpResponse(json.dumps(result))
```

## Deployment

### Via Azure CLI
```bash
func azure functionapp publish <func-name> --python
```

### Via Bicep + Zip Deploy
Include function code as a zip in blob storage, reference in app settings:
```bicep
{ name: 'WEBSITE_RUN_FROM_PACKAGE', value: zipBlobUrl }
```

## Key Gotchas

1. **Flex Consumption is the new default** — Use it over classic Consumption for Python. Better cold start, native virtual network support.
2. **Managed identity for everything** — Function App gets a system-assigned identity. Grant it Search Index Data Reader on AI Search, Cognitive Services OpenAI User on Foundry, and Cosmos Data Contributor on Cosmos DB.
3. **Cold starts** — Python functions have cold starts (~2-5s). For eval runs (many queries), keep the function warm or use a Premium plan.
4. **GraphRAG dependency size** — The `graphrag` package is large (~500MB with dependencies). Use a Linux Consumption plan with remote build, or pre-build a Docker container.
5. **Teardown** — Delete the resource group or the individual Function App + plan. The managed identity and role assignments are cleaned up automatically.
6. **For eval only** — During eval runs, the Function App wraps the search endpoint so the eval runner has a uniform query interface across all architectures. In production, the function may be replaced by a direct SDK call.
