@description('Azure region')
param location string

@description('Tags applied to Container Apps resources')
param tags object

@description('Container Apps managed environment name')
param environmentName string

@description('GraphRAG Container Apps Job name')
param graphJobName string

@description('User-assigned managed identity resource ID')
param managedIdentityResourceId string

@description('Azure Container Registry login server')
param registryServer string

@description('Log Analytics workspace customer ID')
param logAnalyticsCustomerId string

@secure()
@description('Log Analytics workspace shared key')
param logAnalyticsSharedKey string

@description('Application Insights connection string')
param applicationInsightsConnectionString string

@description('Storage account name')
param storageAccountName string

@description('Azure AI Services endpoint')
param aiServicesEndpoint string

@description('Azure AI Search endpoint')
param searchEndpoint string

@description('Chat model deployment name')
param chatModelName string

@description('Embedding model deployment name')
param embeddingModelName string

var placeholderImage = 'mcr.microsoft.com/azuredocs/containerapps-helloworld:latest'
var registryConfiguration = [
  {
    server: registryServer
    identity: managedIdentityResourceId
  }
]

resource managedEnvironment 'Microsoft.App/managedEnvironments@2025-07-01' = {
  name: environmentName
  location: location
  tags: tags
  properties: {
    appLogsConfiguration: {
      destination: 'log-analytics'
      logAnalyticsConfiguration: {
        customerId: logAnalyticsCustomerId
        sharedKey: logAnalyticsSharedKey
      }
    }
    workloadProfiles: [
      {
        name: 'Consumption'
        workloadProfileType: 'Consumption'
      }
      {
        name: 'graph-d4'
        workloadProfileType: 'D4'
        minimumCount: 0
        maximumCount: 1
      }
    ]
    zoneRedundant: false
  }
}

resource graphJob 'Microsoft.App/jobs@2025-07-01' = {
  name: graphJobName
  location: location
  tags: tags
  identity: {
    type: 'UserAssigned'
    userAssignedIdentities: {
      '${managedIdentityResourceId}': {}
    }
  }
  properties: {
    environmentId: managedEnvironment.id
    workloadProfileName: 'graph-d4'
    configuration: {
      triggerType: 'Manual'
      replicaTimeout: 7200
      replicaRetryLimit: 0
      manualTriggerConfig: {
        parallelism: 1
        replicaCompletionCount: 1
      }
      registries: registryConfiguration
    }
    template: {
      containers: [
        {
          name: 'graphrag'
          image: placeholderImage
          resources: {
            cpu: json('2.0')
            memory: '8Gi'
          }
          env: [
            { name: 'AZURE_CLIENT_ID', value: reference(managedIdentityResourceId, '2023-01-31').clientId }
            { name: 'STORAGE_ACCOUNT_NAME', value: storageAccountName }
            { name: 'CORPUS_CONTAINER_NAME', value: 'corpus' }
            { name: 'GRAPH_OUTPUT_CONTAINER', value: 'graphrag' }
            { name: 'AI_SERVICES_ENDPOINT', value: aiServicesEndpoint }
            { name: 'SEARCH_ENDPOINT', value: searchEndpoint }
            { name: 'LLM_DEPLOYMENT_NAME', value: chatModelName }
            { name: 'EMBEDDING_DEPLOYMENT_NAME', value: embeddingModelName }
            { name: 'EMBEDDING_DIMENSIONS', value: '3072' }
            { name: 'APPLICATIONINSIGHTS_CONNECTION_STRING', value: applicationInsightsConnectionString }
            { name: 'GRAPHRAG_METHOD', value: 'fast' }
            { name: 'GRAPHRAG_RUN_SCOPE', value: 'sample' }
            { name: 'GRAPHRAG_MAX_DOCUMENTS', value: '50' }
            { name: 'RETRIEVE_GRAPHRAG_FULL_RUN_APPROVED', value: 'false' }
          ]
        }
      ]
    }
  }
}

output environmentName string = managedEnvironment.name
output graphJobName string = graphJob.name
