// ============================================================================
// Harbormaster Discord bot — Azure Container App deployment
// ============================================================================
// Deploys the bot as a single-replica Container App, with a user-assigned
// managed identity granted Virtual Machine Contributor on the existing game-
// server VM (so it can start, stop, and run PowerShell on it via Run Command).
//
// Prereqs:
//   * Existing resource group (this template is RG-scoped)
//   * Existing Azure Container Registry with the bot image pushed
//   * Existing Windows VM (the game server) in the same RG
// ============================================================================

@description('Location for all bot resources. Defaults to the resource group location.')
param location string = resourceGroup().location

@description('Name prefix used for every resource created here.')
param namePrefix string = 'harbormaster-bot'

@description('Existing Azure Container Registry that holds the bot image.')
param acrName string

@description('Image name and tag inside the ACR (e.g. harbormaster-bot:latest).')
param image string = 'harbormaster-bot:latest'

@description('Name of the existing game-server VM to control.')
param vmName string

@description('Discord bot token. Stored as a Container App secret.')
@secure()
param discordBotToken string

@description('Full bot config as YAML (see bot/config.example.yaml). Stored as a Container App secret and exposed as HARBORMASTER_CONFIG_YAML.')
@secure()
param configYaml string

// --- Existing references --------------------------------------------------

resource acr 'Microsoft.ContainerRegistry/registries@2023-11-01-preview' existing = {
  name: acrName
}

resource vm 'Microsoft.Compute/virtualMachines@2024-03-01' existing = {
  name: vmName
}

// --- Identity -------------------------------------------------------------

resource identity 'Microsoft.ManagedIdentity/userAssignedIdentities@2023-01-31' = {
  name: '${namePrefix}-id'
  location: location
}

// AcrPull on the registry
resource acrPullRole 'Microsoft.Authorization/roleAssignments@2022-04-01' = {
  scope: acr
  name: guid(acr.id, identity.id, 'AcrPull')
  properties: {
    principalId: identity.properties.principalId
    principalType: 'ServicePrincipal'
    roleDefinitionId: subscriptionResourceId(
      'Microsoft.Authorization/roleDefinitions',
      '7f951dda-4ed3-4680-a7ca-43fe172d538d' // AcrPull
    )
  }
}

// Virtual Machine Contributor on the VM (start, stop, run command)
resource vmContributor 'Microsoft.Authorization/roleAssignments@2022-04-01' = {
  scope: vm
  name: guid(vm.id, identity.id, 'VirtualMachineContributor')
  properties: {
    principalId: identity.properties.principalId
    principalType: 'ServicePrincipal'
    roleDefinitionId: subscriptionResourceId(
      'Microsoft.Authorization/roleDefinitions',
      '9980e02c-c2be-4d73-94e8-173b1dc7cf3c' // Virtual Machine Contributor
    )
  }
}

// --- Container Apps environment -------------------------------------------

resource logs 'Microsoft.OperationalInsights/workspaces@2023-09-01' = {
  name: '${namePrefix}-logs'
  location: location
  properties: {
    sku: { name: 'PerGB2018' }
    retentionInDays: 30
  }
}

resource env 'Microsoft.App/managedEnvironments@2024-03-01' = {
  name: '${namePrefix}-env'
  location: location
  properties: {
    appLogsConfiguration: {
      destination: 'log-analytics'
      logAnalyticsConfiguration: {
        customerId: logs.properties.customerId
        sharedKey: logs.listKeys().primarySharedKey
      }
    }
  }
}

// --- Container App --------------------------------------------------------

resource app 'Microsoft.App/containerApps@2024-03-01' = {
  name: namePrefix
  location: location
  identity: {
    type: 'UserAssigned'
    userAssignedIdentities: {
      '${identity.id}': {}
    }
  }
  properties: {
    managedEnvironmentId: env.id
    configuration: {
      activeRevisionsMode: 'Single'
      secrets: [
        {
          name: 'discord-bot-token'
          value: discordBotToken
        }
        {
          name: 'harbormaster-config'
          value: configYaml
        }
      ]
      registries: [
        {
          server: acr.properties.loginServer
          identity: identity.id
        }
      ]
    }
    template: {
      containers: [
        {
          name: 'bot'
          image: '${acr.properties.loginServer}/${image}'
          resources: {
            cpu: json('0.25')
            memory: '0.5Gi'
          }
          env: [
            {
              name: 'DISCORD_BOT_TOKEN'
              secretRef: 'discord-bot-token'
            }
            {
              name: 'HARBORMASTER_CONFIG_YAML'
              secretRef: 'harbormaster-config'
            }
            {
              name: 'AZURE_CLIENT_ID'
              value: identity.properties.clientId
            }
          ]
        }
      ]
      // Discord bots need a persistent gateway connection — keep one replica
      // pinned (no scale-to-zero, no horizontal scale).
      scale: {
        minReplicas: 1
        maxReplicas: 1
      }
    }
  }
  dependsOn: [
    acrPullRole
  ]
}

output containerAppName string = app.name
output identityClientId string = identity.properties.clientId
output identityPrincipalId string = identity.properties.principalId
