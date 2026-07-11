// Azure Cosmos DB for NoSQL (Serverless)
// Used by GraphRAG as the graph artifact store.
// Per skills/azure-cosmos-db.md: Serverless for eval, Provisioned for production.

@description('Cosmos DB account name')
param cosmosAccountName string

@description('Azure region')
param location string = resourceGroup().location

@description('Whether to actually create Cosmos DB resources')
param deployCosmosDB bool = false

@description('Database name')
param databaseName string = 'graphrag'

@description('Container name for graph entities')
param entityContainerName string = 'entities'

@description('Container name for graph communities')
param communityContainerName string = 'communities'

// ── Cosmos DB Account (Serverless) ───────────────────────────────────
// Always deployed — serverless with no containers costs $0.
resource cosmosAccount 'Microsoft.DocumentDB/databaseAccounts@2024-11-15' = if (deployCosmosDB) {
  name: cosmosAccountName
  location: location
  kind: 'GlobalDocumentDB'
  identity: { type: 'SystemAssigned' }
  properties: {
    databaseAccountOfferType: 'Standard'
    locations: [
      {
        locationName: location
        failoverPriority: 0
        isZoneRedundant: false
      }
    ]
    capabilities: [
      { name: 'EnableServerless' }
    ]
    consistencyPolicy: {
      defaultConsistencyLevel: 'Session'
    }
    publicNetworkAccess: 'Enabled'
  }
}

// ── Database ─────────────────────────────────────────────────────────
resource database 'Microsoft.DocumentDB/databaseAccounts/sqlDatabases@2024-11-15' = if (deployCosmosDB) {
  parent: cosmosAccount
  name: databaseName
  properties: {
    resource: {
      id: databaseName
    }
  }
}

// ── Entity Container ─────────────────────────────────────────────────
resource entityContainer 'Microsoft.DocumentDB/databaseAccounts/sqlDatabases/containers@2024-11-15' = if (deployCosmosDB) {
  parent: database
  name: entityContainerName
  properties: {
    resource: {
      id: entityContainerName
      partitionKey: {
        paths: ['/id']
        kind: 'Hash'
        version: 2
      }
      indexingPolicy: {
        indexingMode: 'consistent'
        includedPaths: [{ path: '/*' }]
        excludedPaths: [{ path: '/"_etag"/?' }]
      }
    }
  }
}

// ── Community Container ──────────────────────────────────────────────
resource communityContainer 'Microsoft.DocumentDB/databaseAccounts/sqlDatabases/containers@2024-11-15' = if (deployCosmosDB) {
  parent: database
  name: communityContainerName
  properties: {
    resource: {
      id: communityContainerName
      partitionKey: {
        paths: ['/community_id']
        kind: 'Hash'
        version: 2
      }
    }
  }
}

// ── Outputs ──────────────────────────────────────────────────────────
// NOTE: Data-plane RBAC is handled outside this module after a worker identity exists.
output cosmosAccountId string = deployCosmosDB ? cosmosAccount!.id : ''
output cosmosAccountName string = deployCosmosDB ? cosmosAccount!.name : ''
output cosmosEndpoint string = deployCosmosDB ? cosmosAccount!.properties.documentEndpoint : ''
output cosmosPrincipalId string = deployCosmosDB ? cosmosAccount!.identity.principalId : ''
