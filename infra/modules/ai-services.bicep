@description('Azure region')
param location string

@description('Tags applied to AI Services resources')
param tags object

@description('Azure AI Services account name')
param accountName string

@description('Runtime managed identity principal ID')
param runtimePrincipalId string

@description('Optional deploying principal object ID')
param deployerPrincipalId string = ''

@description('Chat model deployment and model name')
param chatModelName string

@minValue(1)
@description('Chat model capacity in thousands of tokens per minute')
param chatModelCapacity int

@description('Embedding model deployment and model name')
param embeddingModelName string

@minValue(1)
@description('Embedding model capacity in thousands of tokens per minute')
param embeddingModelCapacity int

var openAiUserRoleId = '5e0bd9bd-7b93-4f28-af87-19fc36ad61bd'

resource aiServices 'Microsoft.CognitiveServices/accounts@2025-06-01' = {
  name: accountName
  location: location
  tags: tags
  kind: 'AIServices'
  sku: {
    name: 'S0'
  }
  identity: {
    type: 'SystemAssigned'
  }
  properties: {
    customSubDomainName: accountName
    disableLocalAuth: true
    publicNetworkAccess: 'Enabled'
  }
}

resource embeddingDeployment 'Microsoft.CognitiveServices/accounts/deployments@2025-06-01' = {
  parent: aiServices
  name: embeddingModelName
  sku: {
    name: 'GlobalStandard'
    capacity: embeddingModelCapacity
  }
  properties: {
    model: {
      format: 'OpenAI'
      name: embeddingModelName
      version: '1'
    }
    versionUpgradeOption: 'OnceNewDefaultVersionAvailable'
  }
}

resource chatDeployment 'Microsoft.CognitiveServices/accounts/deployments@2025-06-01' = {
  parent: aiServices
  name: chatModelName
  sku: {
    name: 'GlobalStandard'
    capacity: chatModelCapacity
  }
  properties: {
    model: {
      format: 'OpenAI'
      name: chatModelName
      version: '2025-04-14'
    }
    versionUpgradeOption: 'OnceNewDefaultVersionAvailable'
  }
  dependsOn: [
    embeddingDeployment
  ]
}

resource runtimeOpenAiUser 'Microsoft.Authorization/roleAssignments@2022-04-01' = {
  name: guid(aiServices.id, runtimePrincipalId, openAiUserRoleId)
  scope: aiServices
  properties: {
    roleDefinitionId: subscriptionResourceId('Microsoft.Authorization/roleDefinitions', openAiUserRoleId)
    principalId: runtimePrincipalId
    principalType: 'ServicePrincipal'
  }
}

resource deployerOpenAiUser 'Microsoft.Authorization/roleAssignments@2022-04-01' = if (!empty(deployerPrincipalId)) {
  name: guid(aiServices.id, deployerPrincipalId, openAiUserRoleId, 'deployer')
  scope: aiServices
  properties: {
    roleDefinitionId: subscriptionResourceId('Microsoft.Authorization/roleDefinitions', openAiUserRoleId)
    principalId: deployerPrincipalId
  }
}

output name string = aiServices.name
output resourceId string = aiServices.id
output endpoint string = aiServices.properties.endpoint
output principalId string = aiServices.identity.principalId
