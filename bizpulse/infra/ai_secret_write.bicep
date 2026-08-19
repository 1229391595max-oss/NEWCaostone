metadata description = 'Isolated, package-gated write of one BizPulse OpenAI Key Vault secret.'

param deploymentEnabled bool = false
@minLength(3)
@maxLength(24)
param vaultName string
@secure()
param openAiApiKey string = ''

var validatedOpenAiApiKey = !deploymentEnabled
  ? ''
  : (!empty(openAiApiKey) ? openAiApiKey : fail('openAiApiKey_required_when_deployment_enabled'))

resource vault 'Microsoft.KeyVault/vaults@2025-05-01' existing = {
  name: vaultName
}

resource secret 'Microsoft.KeyVault/vaults/secrets@2025-05-01' = if (deploymentEnabled) {
  parent: vault
  name: 'openai-api-key'
  properties: {
    value: validatedOpenAiApiKey
    attributes: {
      enabled: true
    }
  }
}

output deploymentEnabled bool = deploymentEnabled
output keyVaultSecretName string = deploymentEnabled ? secret!.name : ''
output keyVaultSecretResourceId string = deploymentEnabled ? secret!.id : ''
