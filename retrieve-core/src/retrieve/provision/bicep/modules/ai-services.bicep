// AI Foundry Account + Model Deployments
// Deployed BEFORE Search (Search vectorizer references Foundry endpoint)

@description('AI Services account name')
param aiServicesName string

@description('Azure region')
param location string = resourceGroup().location

@description('Deploy embedding model')
param deployEmbedding bool = true

@description('Embedding model name')
param embeddingModelName string = 'text-embedding-3-large'

@description('Embedding model TPM capacity (thousands)')
param embeddingCapacity int = 100

@description('Deploy LLM model')
param deployLLM bool = false

@description('LLM model name')
param llmModelName string = 'gpt-4.1'

@description('LLM model TPM capacity (thousands)')
param llmCapacity int = 10

resource aiServices 'Microsoft.CognitiveServices/accounts@2025-06-01' = {
  name: aiServicesName
  location: location
  kind: 'AIServices'
  sku: { name: 'S0' }
  identity: { type: 'SystemAssigned' }
  properties: {
    customSubDomainName: aiServicesName
    publicNetworkAccess: 'Enabled'
    disableLocalAuth: false
  }
}

resource embeddingDeployment 'Microsoft.CognitiveServices/accounts/deployments@2025-06-01' = if (deployEmbedding) {
  parent: aiServices
  name: embeddingModelName
  sku: {
    name: 'GlobalStandard'
    capacity: embeddingCapacity
  }
  properties: {
    model: {
      format: 'OpenAI'
      name: embeddingModelName
      version: '1'
    }
  }
}

resource llmDeployment 'Microsoft.CognitiveServices/accounts/deployments@2025-06-01' = if (deployLLM) {
  parent: aiServices
  name: llmModelName
  dependsOn: [embeddingDeployment]  // Sequential model deployments
  sku: {
    name: 'GlobalStandard'
    capacity: llmCapacity
  }
  properties: {
    model: {
      format: 'OpenAI'
      name: llmModelName
      version: '2025-04-14'
    }
  }
}

output aiServicesId string = aiServices.id
output aiServicesName string = aiServices.name
output aiServicesEndpoint string = aiServices.properties.endpoint
output aiServicesPrincipalId string = aiServices.identity.principalId
