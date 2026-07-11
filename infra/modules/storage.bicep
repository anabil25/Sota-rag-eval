@description('Azure region')
param location string

@description('Tags applied to Storage resources')
param tags object

@minLength(3)
@maxLength(24)
@description('Storage account name')
param storageAccountName string

@description('Runtime managed identity principal ID')
param runtimePrincipalId string

@description('Optional deploying principal object ID')
param deployerPrincipalId string = ''

@allowed([
  'Enabled'
  'Disabled'
])
@description('Storage public network access')
param publicNetworkAccess string = 'Enabled'

var blobContributorRoleId = 'ba92f5b4-2d11-453d-a403-e96b0029c9fe'
var corpusContainerName = 'corpus'
var graphContainerName = 'graphrag'

resource storageAccount 'Microsoft.Storage/storageAccounts@2023-05-01' = {
  name: storageAccountName
  location: location
  tags: tags
  sku: {
    name: 'Standard_LRS'
  }
  kind: 'StorageV2'
  properties: {
    accessTier: 'Hot'
    allowBlobPublicAccess: false
    allowSharedKeyAccess: false
    defaultToOAuthAuthentication: true
    minimumTlsVersion: 'TLS1_2'
    publicNetworkAccess: publicNetworkAccess
    supportsHttpsTrafficOnly: true
    networkAcls: {
      bypass: 'AzureServices'
      defaultAction: publicNetworkAccess == 'Enabled' ? 'Allow' : 'Deny'
    }
  }
}

resource blobService 'Microsoft.Storage/storageAccounts/blobServices@2023-05-01' = {
  parent: storageAccount
  name: 'default'
  properties: {
    deleteRetentionPolicy: {
      enabled: true
      days: 7
    }
    containerDeleteRetentionPolicy: {
      enabled: true
      days: 7
    }
  }
}

resource corpusContainer 'Microsoft.Storage/storageAccounts/blobServices/containers@2023-05-01' = {
  parent: blobService
  name: corpusContainerName
  properties: {
    publicAccess: 'None'
  }
}

resource graphContainer 'Microsoft.Storage/storageAccounts/blobServices/containers@2023-05-01' = {
  parent: blobService
  name: graphContainerName
  properties: {
    publicAccess: 'None'
  }
}

resource runtimeBlobContributor 'Microsoft.Authorization/roleAssignments@2022-04-01' = {
  name: guid(storageAccount.id, runtimePrincipalId, blobContributorRoleId)
  scope: storageAccount
  properties: {
    roleDefinitionId: subscriptionResourceId('Microsoft.Authorization/roleDefinitions', blobContributorRoleId)
    principalId: runtimePrincipalId
    principalType: 'ServicePrincipal'
  }
}

resource deployerBlobContributor 'Microsoft.Authorization/roleAssignments@2022-04-01' = if (!empty(deployerPrincipalId)) {
  name: guid(storageAccount.id, deployerPrincipalId, blobContributorRoleId, 'deployer')
  scope: storageAccount
  properties: {
    roleDefinitionId: subscriptionResourceId('Microsoft.Authorization/roleDefinitions', blobContributorRoleId)
    principalId: deployerPrincipalId
  }
}

output name string = storageAccount.name
output resourceId string = storageAccount.id
output blobEndpoint string = storageAccount.properties.primaryEndpoints.blob
output corpusContainerName string = corpusContainer.name
output graphContainerName string = graphContainer.name
