// Azure Container Apps + Managed Environment
// Hosts the LightRAG upstream server image. GraphRAG is deployed by the Python
// provisioner into a dedicated high-memory workload-profile environment because
// Bicep cannot build a local Docker source tree.

@description('Container Apps environment name')
param environmentName string

@description('LightRAG Container App name')
param containerAppName string

@description('Azure region')
param location string = resourceGroup().location

@description('Whether to create the shared Container Apps environment')
param deployContainerApps bool = false

@description('Whether to create the LightRAG server app')
param deployLightRAG bool = false

@description('Container image (LightRAG server)')
param containerImage string = 'ghcr.io/hkuds/lightrag:latest'

@description('AI Services endpoint')
param aiServicesEndpoint string = ''

@description('AI Services resource ID (for scoped RBAC)')
param aiServicesId string = ''

@description('Search endpoint')
param searchEndpoint string = ''

@description('Search service resource ID (for scoped RBAC)')
param searchServiceId string = ''

@description('LLM deployment/model name for LightRAG')
param llmDeploymentName string = 'gpt-4.1'

@description('Embedding deployment/model name for LightRAG')
param embeddingDeploymentName string = 'text-embedding-3-large'

@description('Target port for the LightRAG container')
param targetPort int = 9621

// ── Log Analytics (required by managed environment) ──────────────────
resource logAnalytics 'Microsoft.OperationalInsights/workspaces@2023-09-01' = if (deployContainerApps) {
  name: '${environmentName}-logs'
  location: location
  properties: {
    sku: { name: 'PerGB2018' }
    retentionInDays: 30
  }
}

// ── Container Apps Managed Environment ───────────────────────────────
resource managedEnvironment 'Microsoft.App/managedEnvironments@2025-07-01' = if (deployContainerApps) {
  name: environmentName
  location: location
  properties: {
    appLogsConfiguration: {
      destination: 'log-analytics'
      logAnalyticsConfiguration: {
        customerId: logAnalytics!.properties.customerId
        sharedKey: logAnalytics!.listKeys().primarySharedKey
      }
    }
  }
}

// ── Container App (LightRAG server) ──────────────────────────────────
resource lightragApp 'Microsoft.App/containerApps@2025-07-01' = if (deployContainerApps && deployLightRAG) {
  name: containerAppName
  location: location
  identity: { type: 'SystemAssigned' }
  properties: {
    managedEnvironmentId: managedEnvironment!.id
    configuration: {
      ingress: {
        external: true
        targetPort: targetPort
        transport: 'http'
        allowInsecure: false
      }
      secrets: []
    }
    template: {
      containers: [
        {
          name: 'lightrag'
          image: containerImage
          resources: {
            cpu: json('1.0')
            memory: '2Gi'
          }
          env: [
            { name: 'AI_SERVICES_ENDPOINT', value: aiServicesEndpoint }
            { name: 'SEARCH_ENDPOINT', value: searchEndpoint }
            { name: 'PORT', value: string(targetPort) }
            { name: 'LLM_BINDING', value: 'azure_openai' }
            { name: 'LLM_MODEL', value: llmDeploymentName }
            { name: 'LLM_BINDING_HOST', value: aiServicesEndpoint }
            { name: 'EMBEDDING_BINDING', value: 'azure_openai' }
            { name: 'EMBEDDING_MODEL', value: embeddingDeploymentName }
            { name: 'EMBEDDING_DIM', value: '3072' }
            { name: 'AZURE_OPENAI_ENDPOINT', value: aiServicesEndpoint }
            { name: 'AZURE_OPENAI_DEPLOYMENT', value: llmDeploymentName }
            { name: 'AZURE_OPENAI_EMBEDDING_DEPLOYMENT', value: embeddingDeploymentName }
            { name: 'AZURE_OPENAI_API_VERSION', value: '2025-04-01-preview' }
            { name: 'MAX_PARALLEL_INSERT', value: '1' }
            { name: 'MAX_ASYNC', value: '1' }
            { name: 'EMBEDDING_FUNC_MAX_ASYNC', value: '1' }
            { name: 'EMBEDDING_BATCH_NUM', value: '1' }
            { name: 'EMBEDDING_TIMEOUT', value: '120' }
            { name: 'LLM_TIMEOUT', value: '300' }
          ]
        }
      ]
      scale: {
        minReplicas: 1
        maxReplicas: 1
        rules: [
          {
            name: 'http-scaling'
            http: {
              metadata: {
                concurrentRequests: '10'
              }
            }
          }
        ]
      }
    }
  }
}

resource searchService 'Microsoft.Search/searchServices@2025-05-01' existing = if (!empty(searchServiceId)) {
  name: last(split(searchServiceId, '/'))
}

resource aiServices 'Microsoft.CognitiveServices/accounts@2025-06-01' existing = if (!empty(aiServicesId)) {
  name: last(split(aiServicesId, '/'))
}

var searchIndexDataReaderRoleId = '1407120a-92aa-4202-b7e9-c0e197c71c8f'
var openAIUserRoleId = '5e0bd9bd-7b93-4f28-af87-19fc36ad61bd'

resource lightragSearchReader 'Microsoft.Authorization/roleAssignments@2022-04-01' = if (deployContainerApps && deployLightRAG && !empty(searchServiceId)) {
  name: guid(searchServiceId, containerAppName, searchIndexDataReaderRoleId)
  scope: searchService
  properties: {
    roleDefinitionId: subscriptionResourceId('Microsoft.Authorization/roleDefinitions', searchIndexDataReaderRoleId)
    principalId: lightragApp!.identity.principalId
    principalType: 'ServicePrincipal'
  }
}

resource lightragOpenAIUser 'Microsoft.Authorization/roleAssignments@2022-04-01' = if (deployContainerApps && deployLightRAG && !empty(aiServicesId)) {
  name: guid(aiServicesId, containerAppName, openAIUserRoleId)
  scope: aiServices
  properties: {
    roleDefinitionId: subscriptionResourceId('Microsoft.Authorization/roleDefinitions', openAIUserRoleId)
    principalId: lightragApp!.identity.principalId
    principalType: 'ServicePrincipal'
  }
}

// ── Outputs ──────────────────────────────────────────────────────────
output environmentId string = deployContainerApps ? managedEnvironment!.id : ''
output environmentName string = deployContainerApps ? managedEnvironment!.name : ''
output containerAppId string = (deployContainerApps && deployLightRAG) ? lightragApp!.id : ''
output containerAppName string = (deployContainerApps && deployLightRAG) ? lightragApp!.name : ''
output containerAppEndpoint string = (deployContainerApps && deployLightRAG) ? 'https://${lightragApp!.properties.configuration.ingress.fqdn}' : ''
output containerAppPrincipalId string = (deployContainerApps && deployLightRAG) ? lightragApp!.identity.principalId : ''
