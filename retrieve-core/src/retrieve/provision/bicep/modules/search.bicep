// Azure AI Search Service
// Deployed AFTER Foundry (vectorizer references Foundry endpoint)

@description('Search service name')
param searchServiceName string

@description('Azure region')
param location string = resourceGroup().location

@description('Search SKU')
@allowed(['free', 'basic', 'standard', 'standard2', 'standard3'])
param sku string = 'basic'

@description('Enable semantic search (required for hybrid-reranker)')
@allowed([
  'disabled'
  'free'
  'standard'
])
param semanticSearch string = 'disabled' // 'disabled' | 'free' | 'standard'

resource searchService 'Microsoft.Search/searchServices@2025-05-01' = {
  name: searchServiceName
  location: location
  sku: { name: sku }
  identity: { type: 'SystemAssigned' }
  properties: {
    hostingMode: 'Default'
    publicNetworkAccess: 'enabled'
    semanticSearch: semanticSearch
    authOptions: {
      aadOrApiKey: { aadAuthFailureMode: 'http403' }  // Support both AAD and API key
    }
  }
}

output searchServiceId string = searchService.id
output searchServiceName string = searchService.name
output searchEndpoint string = 'https://${searchService.name}.search.windows.net'
output searchPrincipalId string = searchService.identity.principalId
