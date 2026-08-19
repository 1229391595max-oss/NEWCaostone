using '../operator_rotation_job.bicep'

// The checked-in file is inert. The executor supplies non-secret topology
// parameters from a package-bound public profile and secrets via environment.
param namePrefix = 'needs-auth'
param location = 'requires-authorization'
param containerImage = 'requires-authorization@sha256:0000000000000000000000000000000000000000000000000000000000000000'
param registryName = 'requiresauthorization'
param postgresAdministratorLogin = 'requires-authorization'
param postgresServerName = 'requires-authorization'
param postgresAdministratorPassword = readEnvironmentVariable('BIZPULSE_DEPLOY_POSTGRES_PASSWORD')
param operatorPasswordHash = readEnvironmentVariable('BIZPULSE_DEPLOY_OPERATOR_PASSWORD_HASH')
param sessionPepper = readEnvironmentVariable('BIZPULSE_DEPLOY_SESSION_PEPPER')
param storageAccountName = 'requiresauthstorage'
param operatorRotationEnabled = false
param operatorRotationPasswordHash = readEnvironmentVariable('BIZPULSE_DEPLOY_OPERATOR_ROTATION_PASSWORD_HASH', '')
param operatorRotationExpectedHashFingerprint = readEnvironmentVariable('BIZPULSE_DEPLOY_OPERATOR_ROTATION_EXPECTED_HASH_SHA256', '')
param operatorRotationId = readEnvironmentVariable('BIZPULSE_DEPLOY_OPERATOR_ROTATION_ID', '')
param tags = {
  application: 'newcaostone'
  data_classification: 'pure-synthetic'
  environment: 'demo'
  production_ready: 'false'
}
