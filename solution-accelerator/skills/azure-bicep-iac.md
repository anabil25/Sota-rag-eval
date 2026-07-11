# Skill: Azure Bicep / IaC — Deployment Order, Patterns & Role Assignments

> For: Retrieve solution accelerator — deploying Azure resources via Bicep with correct ordering, managed identity, and role assignment patterns.

## When to Use
- Provisioning any Retrieve architecture (Test Mode or SOTA Eval Mode)
- Understanding resource deployment order (CRITICAL: Foundry before Search)
- Setting up managed identity chains (no keys anywhere)
- Tearing down unselected architectures

## CRITICAL: Deployment Order

```
1. Storage Account + Blob Container     (shared — all architectures)
     ↓
2. AI Foundry / OpenAI Account          (needed by Search vectorizers)
     ↓  model deployments (text-embedding-3-large, gpt-4.1, etc.)
     ↓
3. Azure AI Search Service              (references OpenAI for vectorizers)
     ↓  system-assigned managed identity
     ↓
4. Role Assignments                     (Search → Blob Reader, Search → OpenAI User)
     ↓
5. Cosmos DB Account (GraphRAG only)
     ↓
6. Azure Functions (GraphRAG only)
     ↓  system-assigned managed identity
     ↓
6b. Azure Container Apps (LightRAG only — built-in server)
     ↓
6c. Azure Database for PostgreSQL Flexible Server (LightRAG PG backend only)
     ↓
7. Role Assignments for Functions       (Func → Search, Func → Cosmos, Func → OpenAI)
```

**Why this order matters:**
- Search vectorizer config in the index definition references the OpenAI endpoint + deployment ID. If the OpenAI resource or deployment doesn't exist yet, index creation fails.
- Role assignments reference principal IDs from managed identities, which only exist after the resource is created.
- Blob container must exist before indexer can be configured.

## Bicep Module Structure

```
infra/
  main.bicep                    # Orchestrator — calls modules in order
  modules/
    storage.bicep               # Storage Account + container + deployer role
    ai-services.bicep            # AI Foundry account + model deployments
    search.bicep                 # AI Search service + managed identity
    search-roles.bicep           # Search → Blob Reader, Search → OpenAI
    cosmos.bicep                 # Cosmos DB (GraphRAG only)
    functions.bicep              # Function App + plan (GraphRAG only)
    function-roles.bicep         # Func → Search, Func → Cosmos, Func → OpenAI
    container-apps.bicep         # Container Apps Environment + App (LightRAG only)
    postgresql.bicep             # PostgreSQL Flexible Server + extensions (LightRAG PG backend only)
```

### Main Orchestrator Pattern
```bicep
targetScope = 'resourceGroup'

param namePrefix string
param location string = resourceGroup().location
param deployerObjectId string

// 1. Storage (shared)
module storage 'modules/storage.bicep' = {
  name: 'storage'
  params: {
    namePrefix: namePrefix
    location: location
    deployerObjectId: deployerObjectId
  }
}

// 2. AI Services (must come before Search)
module aiServices 'modules/ai-services.bicep' = {
  name: 'aiServices'
  params: {
    namePrefix: namePrefix
    location: location
  }
}

// 3. Search (references AI Services outputs)
module search 'modules/search.bicep' = {
  name: 'search'
  params: {
    namePrefix: namePrefix
    location: location
  }
  dependsOn: [aiServices]  // CRITICAL
}

// 4. Role assignments (after both Storage and Search exist)
module searchRoles 'modules/search-roles.bicep' = {
  name: 'searchRoles'
  params: {
    storageAccountId: storage.outputs.storageAccountId
    searchPrincipalId: search.outputs.searchPrincipalId
    aiServicesId: aiServices.outputs.aiServicesId
  }
  dependsOn: [storage, search, aiServices]
}
```

## Role Assignment Reference

### Standard Roles Used by Retrieve
| Role Name | Role ID | Assigner → Assignee | Purpose |
|---|---|---|---|
| Storage Blob Data Reader | `2a2b9908-6ea1-4ae2-8e65-a410df84e7d1` | → AI Search | Indexer reads blobs |
| Storage Blob Data Contributor | `ba92f5b4-2d11-453d-a403-e96b0029c9fe` | → Deployer user | Upload scripts write blobs |
| Search Index Data Reader | `1407120a-92aa-4202-b7e9-c0e197c71c8f` | → Function App | Query search indexes |
| Search Index Data Contributor | `8ebe5a00-799e-43f5-93ac-243d3dce84a7` | → Upload script | Push docs to index |
| Search Service Contributor | `7ca78c08-252a-4471-8644-bb5ff32d4ba0` | → Deployer user | Manage indexes, indexers |
| Cognitive Services OpenAI User | `5e0bd9bd-7b93-4f28-af87-19fc36ad61bd` | → AI Search, → Function App | Call embeddings/completions |
| Cosmos DB Data Contributor | Built-in `00000000-...-000002` | → Function App | Read/write graph data |

### Bicep Pattern for Role Assignments
```bicep
param storageAccountId string
param principalId string

var roleId = '2a2b9908-6ea1-4ae2-8e65-a410df84e7d1' // Blob Data Reader

resource roleAssignment 'Microsoft.Authorization/roleAssignments@2022-04-01' = {
  name: guid(storageAccountId, principalId, roleId)
  scope: storageAccount
  properties: {
    roleDefinitionId: subscriptionResourceId('Microsoft.Authorization/roleDefinitions', roleId)
    principalId: principalId
    principalType: 'ServicePrincipal'
  }
}
```

## Per-Architecture Bicep Checklist

| Architecture | Storage | AI Foundry | AI Search | Cosmos DB | Functions | Container Apps | PostgreSQL |
|---|---|---|---|---|---|---|---|
| Keyword only | ✓ | — | ✓ (basic) | — | — | — | — |
| Single vector | ✓ | ✓ (embedding) | ✓ (vector) | — | — | — | — |
| Hybrid | ✓ | ✓ (embedding) | ✓ (hybrid) | — | — | — | — |
| Hybrid + reranker | ✓ | ✓ (embedding) | ✓ (semantic) | — | — | — | — |
| Hybrid + LLM enrichment | ✓ | ✓ (embedding + LLM) | ✓ (semantic) | — | — | — | — |
| Multi-vector (BGE-M3) | ✓ | ✓ (managed compute) | ✓ (multi-vector) | — | — | — | — |
| Agentic (KB) | ✓ | ✓ (embedding + LLM) | ✓ (KB manages index) | — | — | — | — |
| GraphRAG | ✓ | ✓ (embedding + LLM) | ✓ (vector) | ✓ | ✓ (query API) | — | — |
| LightRAG | ✓ | ✓ (embedding + LLM) | ✓ (vector) | — | — | ✓ (built-in server) | ✓ (optional PG backend) |

## Teardown Patterns

### Delete specific resources (preserve shared storage)
```bash
# Delete a search index (doesn't delete the service)
az search index delete --service-name <search> --name <index> -g <rg>

# Delete a model deployment (doesn't delete the account)
az cognitiveservices account deployment delete --name <account> -g <rg> --deployment-name <deployment>

# Delete entire Cosmos DB account (GraphRAG teardown)
az cosmosdb delete --name <cosmos> -g <rg> --yes

# Delete Function App
az functionapp delete --name <func> -g <rg>

# Delete Container App (LightRAG)
az containerapp delete --name <app> -g <rg> --yes

# Delete PostgreSQL Flexible Server (LightRAG PG backend)
az postgres flexible-server delete --name <pg> -g <rg> --yes
```

### Delete entire resource group (full teardown)
```bash
az group delete -n <rg> --yes --no-wait
```

## Key Gotchas

1. **Role assignment propagation delay** — After Bicep creates a role assignment, wait ~30-60 seconds before the identity can actually use it. For indexer runs, add a sleep or retry loop after provisioning.
2. **`dependsOn` is not always sufficient** — Bicep knows about resource creation order but not about Azure AD propagation. If an indexer fails immediately after deployment, it's usually a propagation delay.
3. **Cosmos DB role assignments are different** — Cosmos uses its own `sqlRoleAssignments` resource, not the standard `Microsoft.Authorization/roleAssignments`.
4. **AI Search SKU determines limits** — Free: 3 indexes, 1 indexer. Basic: 15 indexes, 15 indexers. Standard: 50+. For Test Mode with many architectures, you may need Standard or multiple Basic services.
5. **Model deployment quotas** — Each Azure region has TPM (tokens-per-minute) quotas for embeddings. Check with `az cognitiveservices usage list` before deploying.
6. **Idempotent deployments** — All Bicep deployments should be idempotent. Use `CreateOrUpdate` semantics. Re-running `az deployment group create` with the same template should be safe.
