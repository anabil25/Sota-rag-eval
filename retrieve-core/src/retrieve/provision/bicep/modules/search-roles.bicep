// Role assignments for Search → Blob, Search → OpenAI, and Deployer → Blob/Search
// Applied after resource creation — uses managed identity principal IDs

@description('Search service principal ID')
param searchPrincipalId string

@description('Storage account ID (scope for Blob role)')
param storageAccountId string

@description('AI Services account ID (scope for OpenAI role)')
param aiServicesId string = ''

@description('Search service ID (scope for Search contributor roles)')
param searchServiceId string = ''

@description('Assign blob reader role')
param assignBlobReader bool = true

@description('Assign OpenAI user role')
param assignOpenAIUser bool = false

@description('Deployer user object ID (empty = skip deployer roles)')
param deployerObjectId string = ''

// Built-in role definition IDs
var blobDataReaderRoleId = '2a2b9908-6ea1-4ae2-8e65-a410df84e7d1'
var blobDataContributorRoleId = 'ba92f5b4-2d11-453d-a403-e96b0029c9fe'
var cognitiveServicesOpenAIUserRoleId = '5e0bd9bd-7b93-4f28-af87-19fc36ad61bd'
var searchServiceContributorRoleId = '7ca78c08-252a-4471-8644-bb5ff32d4ba0'
var searchIndexDataContributorRoleId = '8ebe5a00-799e-43f5-93ac-243d3dce84a7'

resource storageAccount 'Microsoft.Storage/storageAccounts@2025-06-01' existing = {
  name: last(split(storageAccountId, '/'))
}

resource aiServices 'Microsoft.CognitiveServices/accounts@2025-06-01' existing = if (!empty(aiServicesId)) {
  name: last(split(aiServicesId, '/'))
}

resource searchService 'Microsoft.Search/searchServices@2025-05-01' existing = if (!empty(searchServiceId)) {
  name: last(split(searchServiceId, '/'))
}

// ── Search managed identity roles ────────────────────────────────────
resource blobReaderRole 'Microsoft.Authorization/roleAssignments@2022-04-01' = if (assignBlobReader) {
  name: guid(storageAccountId, searchPrincipalId, blobDataReaderRoleId)
  scope: storageAccount
  properties: {
    roleDefinitionId: subscriptionResourceId('Microsoft.Authorization/roleDefinitions', blobDataReaderRoleId)
    principalId: searchPrincipalId
    principalType: 'ServicePrincipal'
  }
}

resource openAIUserRole 'Microsoft.Authorization/roleAssignments@2022-04-01' = if (assignOpenAIUser && !empty(aiServicesId)) {
  name: guid(aiServicesId, searchPrincipalId, cognitiveServicesOpenAIUserRoleId)
  scope: aiServices
  properties: {
    roleDefinitionId: subscriptionResourceId('Microsoft.Authorization/roleDefinitions', cognitiveServicesOpenAIUserRoleId)
    principalId: searchPrincipalId
    principalType: 'ServicePrincipal'
  }
}

// ── Deployer user roles (upload blobs, manage search indexes) ────────
resource deployerBlobContributor 'Microsoft.Authorization/roleAssignments@2022-04-01' = if (!empty(deployerObjectId)) {
  name: guid(storageAccountId, deployerObjectId, blobDataContributorRoleId)
  scope: storageAccount
  properties: {
    roleDefinitionId: subscriptionResourceId('Microsoft.Authorization/roleDefinitions', blobDataContributorRoleId)
    principalId: deployerObjectId
    principalType: 'User'
  }
}

resource deployerSearchContributor 'Microsoft.Authorization/roleAssignments@2022-04-01' = if (!empty(deployerObjectId) && !empty(searchServiceId)) {
  name: guid(searchServiceId, deployerObjectId, searchServiceContributorRoleId)
  scope: searchService
  properties: {
    roleDefinitionId: subscriptionResourceId('Microsoft.Authorization/roleDefinitions', searchServiceContributorRoleId)
    principalId: deployerObjectId
    principalType: 'User'
  }
}

resource deployerSearchIndexContributor 'Microsoft.Authorization/roleAssignments@2022-04-01' = if (!empty(deployerObjectId) && !empty(searchServiceId)) {
  name: guid(searchServiceId, deployerObjectId, searchIndexDataContributorRoleId)
  scope: searchService
  properties: {
    roleDefinitionId: subscriptionResourceId('Microsoft.Authorization/roleDefinitions', searchIndexDataContributorRoleId)
    principalId: deployerObjectId
    principalType: 'User'
  }
}
