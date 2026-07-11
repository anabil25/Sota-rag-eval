@description('Azure region')
param location string

@description('Tags applied to Search resources')
param tags object

@description('Azure AI Search service name')
param searchServiceName string

@allowed([
  'basic'
  'standard'
])
@description('Azure AI Search SKU')
param skuName string

@description('Runtime managed identity principal ID')
param runtimePrincipalId string

@description('Optional deploying principal object ID')
param deployerPrincipalId string = ''

@description('Storage account name used by Search indexers')
param storageAccountName string

@description('Azure AI Services account name used by Search skills')
param aiServicesName string

var indexDataContributorRoleId = '8ebe5a00-799e-43f5-93ac-243d3dce84a7'
var serviceContributorRoleId = '7ca78c08-252a-4471-8644-bb5ff32d4ba0'
var blobDataReaderRoleId = '2a2b9908-6ea1-4ae2-8e65-a410df84e7d1'
var openAiUserRoleId = '5e0bd9bd-7b93-4f28-af87-19fc36ad61bd'

resource searchService 'Microsoft.Search/searchServices@2025-05-01' = {
  name: searchServiceName
  location: location
  tags: tags
  sku: {
    name: skuName
  }
  identity: {
    type: 'SystemAssigned'
  }
  properties: {
    authOptions: null
    disableLocalAuth: true
    hostingMode: 'Default'
    partitionCount: 1
    publicNetworkAccess: 'enabled'
    replicaCount: 1
    semanticSearch: 'free'
  }
}

resource storageAccount 'Microsoft.Storage/storageAccounts@2023-05-01' existing = {
  name: storageAccountName
}

resource aiServices 'Microsoft.CognitiveServices/accounts@2025-06-01' existing = {
  name: aiServicesName
}

resource runtimeIndexContributor 'Microsoft.Authorization/roleAssignments@2022-04-01' = {
  name: guid(searchService.id, runtimePrincipalId, indexDataContributorRoleId)
  scope: searchService
  properties: {
    roleDefinitionId: subscriptionResourceId('Microsoft.Authorization/roleDefinitions', indexDataContributorRoleId)
    principalId: runtimePrincipalId
    principalType: 'ServicePrincipal'
  }
}

resource runtimeServiceContributor 'Microsoft.Authorization/roleAssignments@2022-04-01' = {
  name: guid(searchService.id, runtimePrincipalId, serviceContributorRoleId)
  scope: searchService
  properties: {
    roleDefinitionId: subscriptionResourceId('Microsoft.Authorization/roleDefinitions', serviceContributorRoleId)
    principalId: runtimePrincipalId
    principalType: 'ServicePrincipal'
  }
}

resource searchBlobReader 'Microsoft.Authorization/roleAssignments@2022-04-01' = {
  name: guid(storageAccount.id, searchService.name, blobDataReaderRoleId)
  scope: storageAccount
  properties: {
    roleDefinitionId: subscriptionResourceId('Microsoft.Authorization/roleDefinitions', blobDataReaderRoleId)
    principalId: searchService.identity.principalId
    principalType: 'ServicePrincipal'
  }
}

resource searchOpenAiUser 'Microsoft.Authorization/roleAssignments@2022-04-01' = {
  name: guid(aiServices.id, searchService.name, openAiUserRoleId)
  scope: aiServices
  properties: {
    roleDefinitionId: subscriptionResourceId('Microsoft.Authorization/roleDefinitions', openAiUserRoleId)
    principalId: searchService.identity.principalId
    principalType: 'ServicePrincipal'
  }
}

resource deployerIndexContributor 'Microsoft.Authorization/roleAssignments@2022-04-01' = if (!empty(deployerPrincipalId)) {
  name: guid(searchService.id, deployerPrincipalId, indexDataContributorRoleId, 'deployer')
  scope: searchService
  properties: {
    roleDefinitionId: subscriptionResourceId('Microsoft.Authorization/roleDefinitions', indexDataContributorRoleId)
    principalId: deployerPrincipalId
  }
}

resource deployerServiceContributor 'Microsoft.Authorization/roleAssignments@2022-04-01' = if (!empty(deployerPrincipalId)) {
  name: guid(searchService.id, deployerPrincipalId, serviceContributorRoleId, 'deployer')
  scope: searchService
  properties: {
    roleDefinitionId: subscriptionResourceId('Microsoft.Authorization/roleDefinitions', serviceContributorRoleId)
    principalId: deployerPrincipalId
  }
}

output name string = searchService.name
output resourceId string = searchService.id
output endpoint string = 'https://${searchService.name}.search.windows.net'
output principalId string = searchService.identity.principalId
