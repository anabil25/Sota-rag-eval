targetScope = 'subscription'

@minLength(1)
@maxLength(64)
@description('Name of the azd environment.')
param environmentName string

@allowed([
  'northcentralus'
  'westus3'
  'centralus'
  'southcentralus'
  'eastus2'
])
@metadata({
  azd: {
    default: 'westus3'
  }
})
@description('Single Azure region used by the complete Retrieve stack.')
param location string

@description('Resource group created for this azd environment.')
param resourceGroupName string = 'rg-${environmentName}'

@description('Object ID of the deploying principal for optional local data-plane access.')
param principalId string = ''

@description('Chat model deployment and model name.')
param chatModelName string = 'gpt-4.1'

@description('Chat model capacity in thousands of tokens per minute.')
@minValue(1)
param chatModelCapacity int = 10

@description('Embedding model deployment and model name.')
param embeddingModelName string = 'text-embedding-3-large'

@description('Embedding model capacity in thousands of tokens per minute.')
@minValue(1)
param embeddingModelCapacity int = 100

@allowed([
  'basic'
  'standard'
])
@description('Azure AI Search SKU.')
param searchSku string = 'basic'

var resourceToken = toLower(uniqueString(subscription().id, location, environmentName))
var resourceTags = {
  'azd-env-name': environmentName
  solution: 'retrieve'
}

resource resourceGroup 'Microsoft.Resources/resourceGroups@2024-03-01' = {
  name: resourceGroupName
  location: location
  tags: {
    'azd-env-name': environmentName
  }
}

module monitoring './modules/monitoring.bicep' = {
  scope: resourceGroup
  params: {
    location: location
    tags: resourceTags
    logAnalyticsName: 'azlaw${resourceToken}'
    applicationInsightsName: 'azins${resourceToken}'
  }
}

module identity './modules/identity.bicep' = {
  scope: resourceGroup
  params: {
    location: location
    tags: resourceTags
    managedIdentityName: 'azid${resourceToken}'
  }
}

module network './modules/network.bicep' = {
  scope: resourceGroup
  params: {
    location: location
    tags: resourceTags
    virtualNetworkName: 'azvnet${resourceToken}'
  }
}

module registry './modules/registry.bicep' = {
  scope: resourceGroup
  params: {
    location: location
    tags: resourceTags
    registryName: 'azcr${resourceToken}'
    runtimePrincipalId: identity.outputs.principalId
    deployerPrincipalId: principalId
  }
}

module storage './modules/storage.bicep' = {
  scope: resourceGroup
  params: {
    location: location
    tags: resourceTags
    storageAccountName: 'azst${resourceToken}'
    runtimePrincipalId: identity.outputs.principalId
    deployerPrincipalId: principalId
    virtualNetworkId: network.outputs.virtualNetworkId
    privateEndpointsSubnetId: network.outputs.privateEndpointsSubnetId
  }
}

module aiServices './modules/ai-services.bicep' = {
  scope: resourceGroup
  params: {
    location: location
    tags: resourceTags
    accountName: 'azai${resourceToken}'
    runtimePrincipalId: identity.outputs.principalId
    deployerPrincipalId: principalId
    chatModelName: chatModelName
    chatModelCapacity: chatModelCapacity
    embeddingModelName: embeddingModelName
    embeddingModelCapacity: embeddingModelCapacity
  }
}

module search './modules/search.bicep' = {
  scope: resourceGroup
  params: {
    location: location
    tags: resourceTags
    searchServiceName: 'azsr${resourceToken}'
    skuName: searchSku
    runtimePrincipalId: identity.outputs.principalId
    deployerPrincipalId: principalId
    storageAccountName: storage.outputs.name
    aiServicesName: aiServices.outputs.name
  }
}

module containerApps './modules/container-apps.bicep' = {
  scope: resourceGroup
  params: {
    location: location
    tags: resourceTags
    environmentName: 'azcae${resourceToken}'
    graphJobName: 'azgrj${resourceToken}'
    managedIdentityResourceId: identity.outputs.resourceId
    infrastructureSubnetId: network.outputs.containerAppsSubnetId
    registryServer: registry.outputs.loginServer
    logAnalyticsCustomerId: monitoring.outputs.logAnalyticsCustomerId
    logAnalyticsSharedKey: monitoring.outputs.logAnalyticsSharedKey
    applicationInsightsConnectionString: monitoring.outputs.applicationInsightsConnectionString
    storageAccountName: storage.outputs.name
    aiServicesEndpoint: aiServices.outputs.endpoint
    searchEndpoint: search.outputs.endpoint
    chatModelName: chatModelName
    chatModelCapacity: chatModelCapacity
    embeddingModelName: embeddingModelName
    embeddingModelCapacity: embeddingModelCapacity
  }
}

output AZURE_RESOURCE_GROUP string = resourceGroup.name
output RESOURCE_GROUP_ID string = resourceGroup.id
output AZURE_LOCATION string = location
output AZURE_RESOURCE_TOKEN string = resourceToken

output AZURE_MANAGED_IDENTITY_NAME string = identity.outputs.name
output AZURE_MANAGED_IDENTITY_CLIENT_ID string = identity.outputs.clientId
output AZURE_MANAGED_IDENTITY_PRINCIPAL_ID string = identity.outputs.principalId
output AZURE_MANAGED_IDENTITY_RESOURCE_ID string = identity.outputs.resourceId

output AZURE_CONTAINER_REGISTRY_NAME string = registry.outputs.name
output AZURE_CONTAINER_REGISTRY_ENDPOINT string = registry.outputs.loginServer

output AZURE_STORAGE_ACCOUNT_NAME string = storage.outputs.name
output AZURE_STORAGE_BLOB_ENDPOINT string = storage.outputs.blobEndpoint
output AZURE_STORAGE_CORPUS_CONTAINER string = storage.outputs.corpusContainerName
output AZURE_STORAGE_GRAPH_CONTAINER string = storage.outputs.graphContainerName

output AZURE_AI_SERVICES_NAME string = aiServices.outputs.name
output AZURE_AI_SERVICES_ENDPOINT string = aiServices.outputs.endpoint
output AZURE_OPENAI_CHAT_DEPLOYMENT string = chatModelName
output AZURE_OPENAI_EMBEDDING_DEPLOYMENT string = embeddingModelName

output AZURE_SEARCH_SERVICE_NAME string = search.outputs.name
output AZURE_SEARCH_ENDPOINT string = search.outputs.endpoint

output AZURE_CONTAINER_APPS_ENVIRONMENT_NAME string = containerApps.outputs.environmentName
output AZURE_GRAPHRAG_JOB_NAME string = containerApps.outputs.graphJobName

output APPLICATIONINSIGHTS_CONNECTION_STRING string = monitoring.outputs.applicationInsightsConnectionString
output AZURE_LOG_ANALYTICS_WORKSPACE_ID string = monitoring.outputs.logAnalyticsId
