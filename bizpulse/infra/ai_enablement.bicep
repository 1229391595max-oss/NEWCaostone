metadata description = 'Isolated BizPulse OpenAI Key Vault and managed identity; inert until exact package approval.'

param deploymentEnabled bool = false
@minLength(3)
@maxLength(16)
param namePrefix string
#disable-next-line no-unused-params
param location string
param logAnalyticsWorkspaceName string
param openaiIdentityName string = take('${namePrefix}-ai-identity', 64)
param openaiKeyVaultName string = take(toLower('${namePrefix}-ai-kv'), 24)

var keyVaultSecretsOfficerRoleDefinitionId = subscriptionResourceId(
  'Microsoft.Authorization/roleDefinitions',
  'b86a8fe4-44ce-4948-aee5-eccb2c155cd7'
)
var keyVaultSecretsUserRoleDefinitionId = subscriptionResourceId(
  'Microsoft.Authorization/roleDefinitions',
  '4633458b-17de-408a-b874-0445c86b69e6'
)

resource openaiIdentity 'Microsoft.ManagedIdentity/userAssignedIdentities@2023-01-31' existing = if (deploymentEnabled) {
  name: openaiIdentityName
}

resource vault 'Microsoft.KeyVault/vaults@2023-07-01' existing = if (deploymentEnabled) {
  name: openaiKeyVaultName
}

resource canonicalSecret 'Microsoft.KeyVault/vaults/secrets@2023-07-01' existing = if (deploymentEnabled) {
  parent: vault
  name: 'openai-api-key'
}

resource adminAiSecretOfficer 'Microsoft.Authorization/roleAssignments@2022-04-01' = if (deploymentEnabled) {
  name: guid(canonicalSecret!.id, openaiIdentity!.id, 'admin-ai-secret-officer')
  scope: canonicalSecret
  properties: {
    principalId: openaiIdentity!.properties.principalId
    principalType: 'ServicePrincipal'
    roleDefinitionId: keyVaultSecretsOfficerRoleDefinitionId
  }
}

resource logWorkspace 'Microsoft.OperationalInsights/workspaces@2023-09-01' existing = if (deploymentEnabled) {
  name: logAnalyticsWorkspaceName
}

resource vaultDiagnostics 'Microsoft.Insights/diagnosticSettings@2021-05-01-preview' = if (deploymentEnabled) {
  name: 'ai-vault-audit'
  scope: vault
  properties: {
    workspaceId: logWorkspace!.id
    logs: [
      {
        category: 'AuditEvent'
        enabled: true
      }
      {
        category: 'AzurePolicyEvaluationDetails'
        enabled: true
      }
    ]
    metrics: [
      {
        category: 'AllMetrics'
        enabled: true
      }
    ]
  }
}

output deploymentEnabled bool = deploymentEnabled
output identityName string = deploymentEnabled ? openaiIdentityName : ''
output identityResourceId string = deploymentEnabled ? openaiIdentity!.id : ''
output managedIdentityClientId string = deploymentEnabled ? openaiIdentity!.properties.clientId : ''
output managedIdentityPrincipalId string = deploymentEnabled ? openaiIdentity!.properties.principalId : ''
output keyVaultName string = deploymentEnabled ? openaiKeyVaultName : ''
output keyVaultResourceId string = deploymentEnabled ? vault!.id : ''
output keyVaultUrl string = deploymentEnabled ? vault!.properties.vaultUri : ''
output canonicalSecretResourceId string = deploymentEnabled ? canonicalSecret!.id : ''
output adminAiSecretOfficerRoleAssignmentResourceId string = deploymentEnabled ? adminAiSecretOfficer!.id : ''
output legacyVaultSecretsUserRoleAssignmentResourceId string = deploymentEnabled
  ? extensionResourceId(
      vault!.id,
      'Microsoft.Authorization/roleAssignments',
      guid(vault!.id, openaiIdentity!.id, keyVaultSecretsUserRoleDefinitionId)
    )
  : ''
