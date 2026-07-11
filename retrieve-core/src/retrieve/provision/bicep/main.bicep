// Retrieve — Main Orchestrator
// Provisions shared resources + per-architecture resources
// Usage: az deployment group create -g <rg> -f main.bicep -p params.json
//
// All three modules always deploy (no conditional modules = no BCP318 warnings).
// An AI Services account with no model deployments costs $0.
// Parameters inside each module control what actually gets created.

@description('Naming prefix for all resources')
param namePrefix string

@description('Azure region')
param location string = resourceGroup().location

@description('Architectures to provision (JSON array)')
param architectures array = ['hybrid']

@description('Embedding model name')
param embeddingModel string = 'text-embedding-3-large'

@description('Embedding model TPM capacity in thousands')
param embeddingCapacity int = 100

@description('LLM model TPM capacity in thousands')
param llmCapacity int = 10

@description('Search SKU')
param searchSku string = 'basic'

@description('Override region for Search (use when primary region is out of capacity)')
param searchLocation string = location

@description('Deployer user object ID (for Blob Contributor + Search Contributor roles)')
param deployerObjectId string = ''

// ── Derived names ────────────────────────────────────────────────────
var storageAccountName = '${namePrefix}store'
var aiServicesName = '${namePrefix}ai'
var searchServiceName = '${namePrefix}-search'

// Determine feature flags from architecture list
var needsEmbedding = length(filter(architectures, arch => arch != 'keyword')) > 0
var needsLLM = length(filter(architectures, arch => contains(['hybrid-llm-enriched', 'agentic-kb', 'graphrag', 'lightrag'], arch))) > 0
var needsSemantic = length(filter(architectures, arch => contains(['hybrid-reranker', 'hybrid-llm-enriched', 'agentic-kb'], arch))) > 0
var needsCosmosDB = length(filter(architectures, arch => arch == 'graphrag')) > 0
var needsGraphRAG = length(filter(architectures, arch => arch == 'graphrag')) > 0
var needsLightRAG = length(filter(architectures, arch => arch == 'lightrag')) > 0
var needsContainerApps = needsLightRAG

// ── Derived names for new modules ────────────────────────────────────
var cosmosAccountName = '${namePrefix}cosmos'
var containerEnvName = '${namePrefix}-env'
var containerAppName = '${namePrefix}-lightrag'
var graphWorkerAppName = '${namePrefix}-graphrag-d4'

// ── 1. Storage (always) ──────────────────────────────────────────────
module storage 'modules/storage.bicep' = {
  name: 'storage'
  params: {
    storageAccountName: storageAccountName
    location: location
  }
}

// ── 2. AI Services (always — costs $0 with no deployments) ───────────
module aiServices 'modules/ai-services.bicep' = {
  name: 'ai-services'
  params: {
    aiServicesName: aiServicesName
    location: location
    deployEmbedding: needsEmbedding
    embeddingModelName: embeddingModel
    embeddingCapacity: embeddingCapacity
    deployLLM: needsLLM
    llmCapacity: llmCapacity
  }
}

// ── 3. AI Search (always — depends on AI Services for vectorizer) ────
module search 'modules/search.bicep' = {
  name: 'search'
  // Search is not logically dependent on Cosmos, but for cross-paradigm
  // deployments we want regional capacity failures in GraphRAG's Cosmos account
  // to fail fast before long-running Search provisioning begins. This lets the
  // provisioner retry the whole stack in the next region instead of waiting on a
  // resource that will be discarded with the failed attempt.
  dependsOn: [
    aiServices
    cosmos
  ]
  params: {
    searchServiceName: searchServiceName
    location: searchLocation
    sku: searchSku
    semanticSearch: needsSemantic ? 'free' : 'disabled'
  }
}

// ── 4. Role Assignments (Search→Blob, Search→OpenAI, Deployer→Blob, Deployer→Search) ──
// Implicit dependsOn via output references
module searchRoles 'modules/search-roles.bicep' = {
  name: 'search-roles'
  params: {
    searchPrincipalId: search.outputs.searchPrincipalId
    storageAccountId: storage.outputs.storageAccountId
    aiServicesId: aiServices.outputs.aiServicesId
    searchServiceId: search.outputs.searchServiceId
    assignBlobReader: true
    assignOpenAIUser: needsEmbedding
    deployerObjectId: deployerObjectId
  }
}

// ── 5. Cosmos DB (GraphRAG only) ─────────────────────────────────────
module cosmos 'modules/cosmos.bicep' = {
  name: 'cosmos'
  params: {
    cosmosAccountName: cosmosAccountName
    location: location
    deployCosmosDB: needsCosmosDB
  }
}

// ── 6. Container Apps environment + LightRAG app ─────────────────────
// GraphRAG uses a dedicated high-memory workload-profile environment created
// by the Python provisioner after ARM creates the shared data services.
module containerApps 'modules/container-apps.bicep' = {
  name: 'container-apps'

  params: {
    environmentName: containerEnvName
    containerAppName: containerAppName
    location: location
    deployContainerApps: needsContainerApps
    deployLightRAG: needsLightRAG
    aiServicesEndpoint: aiServices.outputs.aiServicesEndpoint
    aiServicesId: aiServices.outputs.aiServicesId
    searchEndpoint: search.outputs.searchEndpoint
    searchServiceId: search.outputs.searchServiceId
    llmDeploymentName: 'gpt-4.1'
    embeddingDeploymentName: embeddingModel
  }
}

// ── Outputs ──────────────────────────────────────────────────────────
output storageAccountName string = storage.outputs.storageAccountName
output storageAccountId string = storage.outputs.storageAccountId
output blobEndpoint string = storage.outputs.blobEndpoint
output searchEndpoint string = search.outputs.searchEndpoint
output searchServiceName string = search.outputs.searchServiceName
output searchServiceId string = search.outputs.searchServiceId
output aiServicesEndpoint string = aiServices.outputs.aiServicesEndpoint
output aiServicesName string = aiServices.outputs.aiServicesName
output aiServicesId string = aiServices.outputs.aiServicesId
output cosmosEndpoint string = needsCosmosDB ? cosmos.outputs.cosmosEndpoint : ''
output cosmosAccountName string = needsCosmosDB ? cosmos.outputs.cosmosAccountName : ''
output containerEnvironmentName string = needsContainerApps ? containerApps.outputs.environmentName : ''
output containerAppEndpoint string = needsLightRAG ? containerApps.outputs.containerAppEndpoint : ''
output containerAppName string = needsLightRAG ? containerApps.outputs.containerAppName : ''
output graphWorkerAppName string = needsGraphRAG ? graphWorkerAppName : ''
