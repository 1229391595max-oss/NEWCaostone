using '../main.bicep'

// This checked-in file is deliberately inert. Exact target, region, names, SKUs,
// cost cap, image digest, and secret-bearing values belong only in an explicitly
// approved LAUNCH_AUTHORIZATION.md and a task-owned generated parameter file.
param deploymentEnabled = false
param applicationEnabled = false
param operatorRotationEnabled = false
param operatorRotationPasswordHash = readEnvironmentVariable('BIZPULSE_DEPLOY_OPERATOR_ROTATION_PASSWORD_HASH', '')
param operatorRotationExpectedHashFingerprint = readEnvironmentVariable('BIZPULSE_DEPLOY_OPERATOR_ROTATION_EXPECTED_HASH_SHA256', '')
param operatorRotationId = readEnvironmentVariable('BIZPULSE_DEPLOY_OPERATOR_ROTATION_ID', '')
param namePrefix = 'needs-auth'
param location = 'requires-authorization'
param containerImage = 'requires-authorization@sha256:0000000000000000000000000000000000000000000000000000000000000000'
param syntheticManifestSha256 = '0000000000000000000000000000000000000000000000000000000000000000'
param syntheticDatasetVersionId = 'requires-authorization-dataset-id-00'
param registryName = 'requiresauthorization'
param postgresAdministratorLogin = 'requires-authorization'
param postgresServerName = 'requires-authorization'
param postgresAdministratorPassword = readEnvironmentVariable('BIZPULSE_DEPLOY_POSTGRES_PASSWORD')
param operatorPasswordHash = readEnvironmentVariable('BIZPULSE_DEPLOY_OPERATOR_PASSWORD_HASH')
param sessionPepper = readEnvironmentVariable('BIZPULSE_DEPLOY_SESSION_PEPPER')
param openaiKeyVaultUrl = ''
param openaiManagedIdentityClientId = ''
param openaiManagedIdentityResourceId = ''
param aiChatEnabled = false
param storageSku = 'requires-authorization'
param storageAccountName = 'requiresauthstorage'
param postgresSkuName = 'requires-authorization'
param postgresTier = 'requires-authorization'
param postgresStorageSizeGb = 32
param postgresBackupRetentionDays = 7
param logRetentionDays = 30
