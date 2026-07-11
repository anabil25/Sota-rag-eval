@description('Azure region')
param location string

@description('Tags applied to the managed identity')
param tags object

@description('User-assigned managed identity name')
param managedIdentityName string

resource managedIdentity 'Microsoft.ManagedIdentity/userAssignedIdentities@2023-01-31' = {
  name: managedIdentityName
  location: location
  tags: tags
}

output name string = managedIdentity.name
output resourceId string = managedIdentity.id
output principalId string = managedIdentity.properties.principalId
output clientId string = managedIdentity.properties.clientId
