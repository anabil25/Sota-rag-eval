@description('Azure region')
param location string

@description('Tags applied to the registry')
param tags object

@minLength(5)
@maxLength(50)
@description('Azure Container Registry name')
param registryName string

@description('Runtime managed identity principal ID')
param runtimePrincipalId string

@description('Optional deploying principal object ID')
param deployerPrincipalId string = ''

var acrPullRoleId = '7f951dda-4ed3-4680-a7ca-43fe172d538d'
var acrTasksContributorRoleId = 'fb382eab-e894-4461-af04-94435c366c3f'

resource registry 'Microsoft.ContainerRegistry/registries@2023-11-01-preview' = {
  name: registryName
  location: location
  tags: tags
  sku: {
    name: 'Basic'
  }
  properties: {
    adminUserEnabled: false
    publicNetworkAccess: 'Enabled'
    policies: {
      azureADAuthenticationAsArmPolicy: {
        status: 'enabled'
      }
    }
  }
}

resource runtimeAcrPull 'Microsoft.Authorization/roleAssignments@2022-04-01' = {
  name: guid(registry.id, runtimePrincipalId, acrPullRoleId)
  scope: registry
  properties: {
    roleDefinitionId: subscriptionResourceId('Microsoft.Authorization/roleDefinitions', acrPullRoleId)
    principalId: runtimePrincipalId
    principalType: 'ServicePrincipal'
  }
}

resource deployerAcrTasksContributor 'Microsoft.Authorization/roleAssignments@2022-04-01' = if (!empty(deployerPrincipalId)) {
  name: guid(registry.id, deployerPrincipalId, acrTasksContributorRoleId)
  scope: registry
  properties: {
    roleDefinitionId: subscriptionResourceId('Microsoft.Authorization/roleDefinitions', acrTasksContributorRoleId)
    principalId: deployerPrincipalId
  }
}

output name string = registry.name
output resourceId string = registry.id
output loginServer string = registry.properties.loginServer
