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
var acrPushRoleId = '8311e382-0749-4cb8-b61a-304f252e45ec'

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

resource deployerAcrPush 'Microsoft.Authorization/roleAssignments@2022-04-01' = if (!empty(deployerPrincipalId)) {
  name: guid(registry.id, deployerPrincipalId, acrPushRoleId)
  scope: registry
  properties: {
    roleDefinitionId: subscriptionResourceId('Microsoft.Authorization/roleDefinitions', acrPushRoleId)
    principalId: deployerPrincipalId
  }
}

output name string = registry.name
output resourceId string = registry.id
output loginServer string = registry.properties.loginServer
