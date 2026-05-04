// ============================================================================
// Harbormaster Discord bot — Azure Container App deployment
// ============================================================================
// Deploys the bot as a single-replica Container App, with a user-assigned
// managed identity granted:
//   * AcrPull on the existing Azure Container Registry
//   * Virtual Machine Contributor on the existing game-server VM
//   * Key Vault Secrets User on the existing Key Vault that holds the bot's
//     runtime secrets (discord-bot-token, harbormaster-config)
//
// Runtime secrets are *referenced* from Key Vault, not passed in as
// parameters. That means CI/CD pipelines (and ARM deployment history) never
// see the actual values — the Container App fetches them at startup via
// managed identity.
//
// Prereqs (deploy these once, separately):
//   * Resource group (this template is RG-scoped)
//   * Azure Container Registry with the bot image pushed
//   * Windows VM (the game server) in the same RG
//   * Key Vault with secrets `discord-bot-token` and `harbormaster-config`
//     seeded (see infra/keyvault.bicep)
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

@description('Existing Key Vault that holds the bot runtime secrets.')
param keyVaultName string

@description('Resource group of the Key Vault. Defaults to the current resource group.')
param keyVaultResourceGroup string = resourceGroup().name

@description('Name of the Key Vault secret holding the Discord bot token.')
param discordTokenSecretName string = 'discord-bot-token'

@description('Name of the Key Vault secret holding the full bot config YAML.')
param configYamlSecretName string = 'harbormaster-config'

// --- Existing references --------------------------------------------------

resource acr 'Microsoft.ContainerRegistry/registries@2023-11-01-preview' existing = {
  name: acrName
}

resource vm 'Microsoft.Compute/virtualMachines@2024-03-01' existing = {
  name: vmName
}

resource kv 'Microsoft.KeyVault/vaults@2023-07-01' existing = {
  name: keyVaultName
  scope: resourceGroup(keyVaultResourceGroup)
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

// Key Vault Secrets User on the Key Vault (read secrets only).
// Scoped via a nested module so the KV may live in a different RG.
module kvRole 'kv-role.bicep' = {
  name: 'kv-secrets-user'
  scope: resourceGroup(keyVaultResourceGroup)
  params: {
    keyVaultName: keyVaultName
    principalId: identity.properties.principalId
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
      // Container Apps natively supports Key Vault secret references: the
      // platform fetches the latest secret value using the linked managed
      // identity at revision start, and re-fetches on revision restart.
      // The actual secret value never appears in this template, in
      // deployment history, or in the CI pipeline.
      secrets: [
        {
          name: 'discord-bot-token'
          keyVaultUrl: '${kv.properties.vaultUri}secrets/${discordTokenSecretName}'
          identity: identity.id
        }
        {
          name: 'harbormaster-config'
          keyVaultUrl: '${kv.properties.vaultUri}secrets/${configYamlSecretName}'
          identity: identity.id
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
    kvRole
  ]
}

output containerAppName string = app.name
output identityClientId string = identity.properties.clientId
output identityPrincipalId string = identity.properties.principalId
