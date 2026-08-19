metadata description = 'Fail-closed Azure Demo topology; inert until an exact launch package enables it.'

param deploymentEnabled bool = false
param applicationEnabled bool = false
param operatorRotationEnabled bool = false
@secure()
param operatorRotationPasswordHash string = ''
param operatorRotationExpectedHashFingerprint string = ''
param operatorRotationId string = ''
@maxLength(32)
param applicationRevisionSuffix string = ''
@minLength(3)
@maxLength(18)
param namePrefix string
param location string
param containerImage string
@minLength(64)
@maxLength(64)
param syntheticManifestSha256 string
@minLength(36)
@maxLength(36)
param syntheticDatasetVersionId string
param registryName string
param postgresAdministratorLogin string
@minLength(3)
@maxLength(63)
param postgresServerName string
@secure()
param postgresAdministratorPassword string
@secure()
param operatorPasswordHash string
@secure()
param sessionPepper string
param openaiKeyVaultUrl string = ''
param openaiManagedIdentityClientId string = ''
param openaiManagedIdentityResourceId string = ''
param aiChatEnabled bool = false
param aiBudgetFailureRehearsal bool = false
@minValue(120)
@maxValue(120)
param aiDailyAttemptLimit int = 120
@minValue(150000)
@maxValue(150000)
param aiMonthlyTokenLimit int = 150000
@minValue(15)
@maxValue(15)
param aiMaxConcurrentTurns int = 15
@minValue(3)
@maxValue(3)
param aiSessionAttemptLimitPerMinute int = 3
@minValue(20)
@maxValue(20)
param aiGlobalAttemptLimitPerMinute int = 20
param demoSessionRateLimitPerHour int = 50
param storageSku string
@minLength(3)
@maxLength(24)
param storageAccountName string
param postgresSkuName string
param postgresTier string
param postgresStorageSizeGb int
param postgresBackupRetentionDays int
param logRetentionDays int
param vnetAddressPrefix string = '10.40.0.0/16'
param appSubnetPrefix string = '10.40.0.0/23'
param postgresSubnetPrefix string = '10.40.2.0/24'
param tags object = {
  application: 'newcaostone'
  data_classification: 'pure-synthetic'
  environment: 'demo'
  production_ready: 'false'
}

var containerImageParts = split(containerImage, '@sha256:')
var containerImageDigest = length(containerImageParts) == 2 ? containerImageParts[1] : ''
var containerImageDigestRemainder = replace(replace(replace(replace(replace(replace(replace(replace(replace(replace(replace(replace(replace(replace(replace(replace(toLower(containerImageDigest), '0', ''), '1', ''), '2', ''), '3', ''), '4', ''), '5', ''), '6', ''), '7', ''), '8', ''), '9', ''), 'a', ''), 'b', ''), 'c', ''), 'd', ''), 'e', ''), 'f', '')
var containerImageIsImmutable = length(containerImageParts) == 2 && !empty(containerImageParts[0]) && length(containerImageDigest) == 64 && empty(containerImageDigestRemainder)
var validatedContainerImage = !deploymentEnabled ? containerImage : (containerImageIsImmutable ? containerImage : fail('containerImage_must_be_immutable_digest'))
var validatedAiChatEnabled = !aiChatEnabled
  ? false
  : (applicationEnabled ? true : fail('aiChatEnabled_requires_enabled_application'))
var openaiKeyVaultUrlParts = split(openaiKeyVaultUrl, '/')
var openaiKeyVaultUrlIsCanonical = length(openaiKeyVaultUrlParts) == 4 ? openaiKeyVaultUrlParts[0] == 'https:' && empty(openaiKeyVaultUrlParts[1]) && endsWith(openaiKeyVaultUrlParts[2], '.${environment().suffixes.keyvaultDns}') && empty(openaiKeyVaultUrlParts[3]) && toLower(openaiKeyVaultUrl) == openaiKeyVaultUrl : false
var validatedOpenaiKeyVaultUrl = !validatedAiChatEnabled
  ? (empty(openaiKeyVaultUrl) ? '' : fail('openaiKeyVaultUrl_must_be_empty_when_ai_disabled'))
  : (openaiKeyVaultUrlIsCanonical ? openaiKeyVaultUrl : fail('openaiKeyVaultUrl_required_when_ai_enabled'))
var validatedOpenaiManagedIdentityClientId = !validatedAiChatEnabled
  ? (empty(openaiManagedIdentityClientId) ? '' : fail('openaiManagedIdentityClientId_must_be_empty_when_ai_disabled'))
  : (length(openaiManagedIdentityClientId) == 36 ? openaiManagedIdentityClientId : fail('openaiManagedIdentityClientId_required_when_ai_enabled'))
var validatedOpenaiManagedIdentityResourceId = !validatedAiChatEnabled
  ? (empty(openaiManagedIdentityResourceId) ? '' : fail('openaiManagedIdentityResourceId_must_be_empty_when_ai_disabled'))
  : (contains(toLower(openaiManagedIdentityResourceId), '/providers/microsoft.managedidentity/userassignedidentities/') ? openaiManagedIdentityResourceId : fail('openaiManagedIdentityResourceId_required_when_ai_enabled'))
var validatedAiBudgetFailureRehearsal = !aiBudgetFailureRehearsal
  ? false
  : (validatedAiChatEnabled ? true : fail('aiBudgetFailureRehearsal_requires_enabled_application'))
var validatedOperatorRotationExpectedHashFingerprint = !operatorRotationEnabled
  ? ''
  : (length(operatorRotationExpectedHashFingerprint) == 64
    ? operatorRotationExpectedHashFingerprint
    : fail('operatorRotationExpectedHashFingerprint_must_be_64_characters'))
var validatedOperatorRotationPasswordHash = !operatorRotationEnabled
  ? ''
  : (!empty(operatorRotationPasswordHash)
    ? operatorRotationPasswordHash
    : fail('operatorRotationPasswordHash_required_when_enabled'))
var validatedOperatorRotationId = !operatorRotationEnabled
  ? ''
  : (length(operatorRotationId) == 64
    ? operatorRotationId
    : fail('operatorRotationId_must_be_64_characters'))
var selectedRevisionSuffix = !empty(applicationRevisionSuffix)
  ? applicationRevisionSuffix
  : (applicationEnabled ? take(containerImageDigest, 12) : 'prep-${take(containerImageDigest, 7)}')

var blobContainer = 'synthetic-demo'
var logWorkspaceName = take('${namePrefix}-logs', 63)
var registryIdentityName = take('${namePrefix}-registry', 64)
var acrPullRoleDefinitionId = subscriptionResourceId(
  'Microsoft.Authorization/roleDefinitions',
  '7f951dda-4ed3-4680-a7ca-43fe172d538d'
)

resource registry 'Microsoft.ContainerRegistry/registries@2023-07-01' existing = if (deploymentEnabled) {
  name: registryName
}

resource registryIdentity 'Microsoft.ManagedIdentity/userAssignedIdentities@2023-01-31' = if (deploymentEnabled) {
  name: registryIdentityName
  location: location
  tags: tags
}

resource registryPullAssignment 'Microsoft.Authorization/roleAssignments@2022-04-01' = if (deploymentEnabled) {
  name: guid(registry!.id, registryIdentity!.id, acrPullRoleDefinitionId)
  scope: registry
  properties: {
    principalId: registryIdentity!.properties.principalId
    principalType: 'ServicePrincipal'
    roleDefinitionId: acrPullRoleDefinitionId
  }
}

module monitoring 'modules/monitoring.bicep' = if (deploymentEnabled) {
  name: 'monitoring'
  params: {
    location: location
    namePrefix: namePrefix
    workspaceName: logWorkspaceName
    retentionDays: logRetentionDays
    tags: tags
  }
}

module storage 'modules/storage.bicep' = if (deploymentEnabled) {
  name: 'storage'
  params: {
    location: location
    storageAccountName: storageAccountName
    containerName: blobContainer
    storageSku: storageSku
    tags: tags
  }
}

module postgres 'modules/postgres.bicep' = if (deploymentEnabled) {
  name: 'postgres'
  params: {
    location: location
    namePrefix: namePrefix
    administratorLogin: postgresAdministratorLogin
    administratorPassword: postgresAdministratorPassword
    postgresServerName: postgresServerName
    postgresSkuName: postgresSkuName
    postgresTier: postgresTier
    postgresStorageSizeGb: postgresStorageSizeGb
    postgresBackupRetentionDays: postgresBackupRetentionDays
    vnetAddressPrefix: vnetAddressPrefix
    appSubnetPrefix: appSubnetPrefix
    postgresSubnetPrefix: postgresSubnetPrefix
    tags: tags
  }
}

var databaseUrl = deploymentEnabled
  ? 'postgresql+psycopg://${uriComponent(postgresAdministratorLogin)}:${uriComponent(postgresAdministratorPassword)}@${postgres!.outputs.serverFqdn}:5432/${postgres!.outputs.databaseName}?sslmode=require&connect_timeout=2'
  : ''

module application 'modules/app.bicep' = if (deploymentEnabled) {
  name: 'application'
  params: {
    location: location
    namePrefix: namePrefix
    containerImage: validatedContainerImage
    syntheticManifestSha256: syntheticManifestSha256
    syntheticDatasetVersionId: syntheticDatasetVersionId
    revisionSuffix: selectedRevisionSuffix
    applicationEnabled: applicationEnabled
    operatorRotationEnabled: operatorRotationEnabled
    operatorRotationPasswordHash: validatedOperatorRotationPasswordHash
    operatorRotationExpectedHashFingerprint: validatedOperatorRotationExpectedHashFingerprint
    operatorRotationId: validatedOperatorRotationId
    appSubnetId: postgres!.outputs.appSubnetId
    logAnalyticsCustomerId: monitoring!.outputs.workspaceCustomerId
    logAnalyticsWorkspaceName: logWorkspaceName
    applicationInsightsConnectionString: monitoring!.outputs.applicationInsightsConnectionString
    registryServer: '${registryName}.azurecr.io'
    registryIdentityResourceId: registryIdentity!.id
    databaseUrl: databaseUrl
    blobEndpoint: storage!.outputs.blobEndpoint
    blobContainer: storage!.outputs.containerName
    storageAccountName: storage!.outputs.accountName
    operatorPasswordHash: operatorPasswordHash
    sessionPepper: sessionPepper
    openaiKeyVaultUrl: validatedOpenaiKeyVaultUrl
    openaiManagedIdentityClientId: validatedOpenaiManagedIdentityClientId
    openaiManagedIdentityResourceId: validatedOpenaiManagedIdentityResourceId
    aiChatEnabled: validatedAiChatEnabled
    aiBudgetFailureRehearsal: validatedAiBudgetFailureRehearsal
    aiDailyAttemptLimit: aiDailyAttemptLimit
    aiMonthlyTokenLimit: aiMonthlyTokenLimit
    aiMaxConcurrentTurns: aiMaxConcurrentTurns
    aiSessionAttemptLimitPerMinute: aiSessionAttemptLimitPerMinute
    aiGlobalAttemptLimitPerMinute: aiGlobalAttemptLimitPerMinute
    demoSessionRateLimitPerHour: demoSessionRateLimitPerHour
    tags: tags
  }
  dependsOn: [
    registryPullAssignment
  ]
}

output deploymentEnabled bool = deploymentEnabled
output applicationEnabled bool = applicationEnabled
output publicUrl string = deploymentEnabled && applicationEnabled ? application!.outputs.publicUrl : ''
output migrationJobName string = deploymentEnabled ? application!.outputs.migrationJobName : ''
output seedJobName string = deploymentEnabled ? application!.outputs.seedJobName : ''
output operatorRotationJobName string = deploymentEnabled ? application!.outputs.operatorRotationJobName : ''
output applicationRevisionName string = deploymentEnabled && applicationEnabled ? application!.outputs.revisionName : ''
output postgresServerId string = deploymentEnabled ? postgres!.outputs.serverId : ''
output storageAccountId string = deploymentEnabled ? storage!.outputs.accountId : ''
