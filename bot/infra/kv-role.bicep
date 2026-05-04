// ============================================================================
// Helper module: assign "Key Vault Secrets User" to a principal.
// Lives in its own module so it can target the Key Vault's resource group,
// even when that RG differs from the bot's RG.
// ============================================================================

@description('Name of the existing Key Vault to grant access on.')
param keyVaultName string

@description('Object/principal ID of the identity to grant access to.')
param principalId string

resource kv 'Microsoft.KeyVault/vaults@2023-07-01' existing = {
  name: keyVaultName
}

resource secretsUser 'Microsoft.Authorization/roleAssignments@2022-04-01' = {
  scope: kv
  name: guid(kv.id, principalId, 'KeyVaultSecretsUser')
  properties: {
    principalId: principalId
    principalType: 'ServicePrincipal'
    roleDefinitionId: subscriptionResourceId(
      'Microsoft.Authorization/roleDefinitions',
      '4633458b-17de-408a-b874-0445c86b69e6' // Key Vault Secrets User
    )
  }
}
