// ============================================================================
// Harbormaster bot — Key Vault for runtime secrets
// ============================================================================
// One-time provisioning of the Key Vault that holds the bot's runtime
// secrets (Discord bot token, full config YAML). Kept in a separate template
// so the main bot.bicep can be re-deployed by CI/CD without touching the KV
// or its access policies.
//
// After deployment, seed the secrets with:
//
//   az keyvault secret set --vault-name <kv-name> \
//     --name discord-bot-token --value '<token>'
//   az keyvault secret set --vault-name <kv-name> \
//     --name harbormaster-config --file ./config.yaml
//
// The bot's user-assigned managed identity is granted "Key Vault Secrets
// User" by bot.bicep, so it can read these at runtime without ever putting
// the values into deployment parameters or pipeline logs.
// ============================================================================

@description('Location for the Key Vault. Defaults to the resource group location.')
param location string = resourceGroup().location

@description('Globally unique Key Vault name (3-24 chars, alphanumeric + hyphen).')
param keyVaultName string

@description('Tenant ID. Defaults to the deploying tenant.')
param tenantId string = subscription().tenantId

resource kv 'Microsoft.KeyVault/vaults@2023-07-01' = {
  name: keyVaultName
  location: location
  properties: {
    tenantId: tenantId
    sku: {
      family: 'A'
      name: 'standard'
    }
    // RBAC mode — role assignments are how the bot identity gets read access.
    // No legacy access policies.
    enableRbacAuthorization: true
    enableSoftDelete: true
    softDeleteRetentionInDays: 7
    enablePurgeProtection: true
    publicNetworkAccess: 'Enabled'
  }
}

output keyVaultName string = kv.name
output keyVaultUri string = kv.properties.vaultUri
output keyVaultId string = kv.id
