@description('Azure region')
param location string

@description('Tags applied to network resources')
param tags object

@description('Virtual network name')
param virtualNetworkName string

@description('Create the delegated subnet used only by the GraphRAG experiment runtime')
param deployGraphRuntime bool = false

resource virtualNetwork 'Microsoft.Network/virtualNetworks@2024-05-01' = {
  name: virtualNetworkName
  location: location
  tags: tags
  properties: {
    addressSpace: {
      addressPrefixes: [
        '10.42.0.0/16'
      ]
    }
  }
}

resource containerAppsSubnet 'Microsoft.Network/virtualNetworks/subnets@2024-05-01' = if (deployGraphRuntime) {
  parent: virtualNetwork
  name: 'container-apps'
  properties: {
    addressPrefix: '10.42.0.0/23'
    delegations: [
      {
        name: 'Microsoft.App-environments'
        properties: {
          serviceName: 'Microsoft.App/environments'
        }
      }
    ]
  }
}

resource privateEndpointsSubnet 'Microsoft.Network/virtualNetworks/subnets@2024-05-01' = {
  parent: virtualNetwork
  name: 'private-endpoints'
  properties: {
    addressPrefix: '10.42.2.0/24'
    privateEndpointNetworkPolicies: 'Disabled'
  }
}

output virtualNetworkId string = virtualNetwork.id
output containerAppsSubnetId string = containerAppsSubnet.?id ?? ''
output privateEndpointsSubnetId string = privateEndpointsSubnet.id
