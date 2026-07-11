// Cosmos DB SQL data-plane RBAC.
// Assigns the built-in Data Contributor role without redeploying data resources.

@description('Cosmos DB account name')
param cosmosAccountName string

@description('Principal ID that needs Cosmos DB data contributor access')
param dataContributorPrincipalId string

resource cosmosAccount 'Microsoft.DocumentDB/databaseAccounts@2024-11-15' existing = {
  name: cosmosAccountName
}

// Built-in "Cosmos DB Built-in Data Contributor" role ID.
var cosmosDataContributorRoleId = '00000000-0000-0000-0000-000000000002'

resource dataContributorRole 'Microsoft.DocumentDB/databaseAccounts/sqlRoleAssignments@2024-11-15' = {
  parent: cosmosAccount
  name: guid(cosmosAccount.id, dataContributorPrincipalId, cosmosDataContributorRoleId)
  properties: {
    roleDefinitionId: '${cosmosAccount.id}/sqlRoleDefinitions/${cosmosDataContributorRoleId}'
    principalId: dataContributorPrincipalId
    scope: cosmosAccount.id
  }
}
