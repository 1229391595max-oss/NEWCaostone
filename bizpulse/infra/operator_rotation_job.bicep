metadata description = 'A fail-closed, job-only deployment surface for one operator password rotation.'

@minLength(3)
@maxLength(18)
param namePrefix string
param location string
param containerImage string
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
@minLength(3)
@maxLength(24)
param storageAccountName string
param operatorRotationEnabled bool = false
@secure()
param operatorRotationPasswordHash string = ''
param operatorRotationExpectedHashFingerprint string = ''
param operatorRotationId string = ''
param tags object

var containerImageParts = split(containerImage, '@sha256:')
var containerImageDigest = length(containerImageParts) == 2 ? containerImageParts[1] : ''
var containerImageDigestRemainder = replace(replace(replace(replace(replace(replace(replace(replace(replace(replace(replace(replace(replace(replace(replace(replace(toLower(containerImageDigest), '0', ''), '1', ''), '2', ''), '3', ''), '4', ''), '5', ''), '6', ''), '7', ''), '8', ''), '9', ''), 'a', ''), 'b', ''), 'c', ''), 'd', ''), 'e', ''), 'f', '')
var containerImageIsImmutable = length(containerImageParts) == 2 && !empty(containerImageParts[0]) && length(containerImageDigest) == 64 && empty(containerImageDigestRemainder)
var validatedContainerImage = containerImageIsImmutable ? containerImage : fail('containerImage_must_be_immutable_digest')
var validatedOperatorPasswordHash = !empty(operatorPasswordHash) ? operatorPasswordHash : fail('operatorPasswordHash_required')
var validatedRotationPasswordHash = !operatorRotationEnabled
  ? ''
  : (!empty(operatorRotationPasswordHash)
    ? operatorRotationPasswordHash
    : fail('operatorRotationPasswordHash_required_when_enabled'))
var validatedRotationExpectedHashFingerprint = !operatorRotationEnabled
  ? ''
  : (length(operatorRotationExpectedHashFingerprint) == 64
    ? operatorRotationExpectedHashFingerprint
    : fail('operatorRotationExpectedHashFingerprint_must_be_64_characters'))
var validatedRotationId = !operatorRotationEnabled
  ? ''
  : (length(operatorRotationId) == 64
    ? operatorRotationId
    : fail('operatorRotationId_must_be_64_characters'))

var appName = take('${namePrefix}-app', 32)
var environmentName = take('${namePrefix}-env', 60)
var registryIdentityName = take('${namePrefix}-registry', 64)
var rotationJobName = take('${namePrefix}-rotate-operator', 32)
var blobContainer = 'synthetic-demo'

resource environment 'Microsoft.App/managedEnvironments@2024-03-01' existing = {
  name: environmentName
}

resource registryIdentity 'Microsoft.ManagedIdentity/userAssignedIdentities@2023-01-31' existing = {
  name: registryIdentityName
}

resource storageAccount 'Microsoft.Storage/storageAccounts@2023-05-01' existing = {
  name: storageAccountName
}

resource postgresServer 'Microsoft.DBforPostgreSQL/flexibleServers@2024-08-01' existing = {
  name: postgresServerName
}

var storageAccountKey = storageAccount.listKeys().keys[0].value
var blobConnectionString = 'DefaultEndpointsProtocol=https;AccountName=${storageAccount.name};AccountKey=${storageAccountKey};EndpointSuffix=${az.environment().suffixes.storage}'
var databaseUrl = 'postgresql+psycopg://${uriComponent(postgresAdministratorLogin)}:${uriComponent(postgresAdministratorPassword)}@${postgresServer.properties.fullyQualifiedDomainName}:5432/bizpulse?sslmode=require&connect_timeout=2'
var publicUrl = 'https://${appName}.${environment.properties.defaultDomain}'
var registryConfiguration = [
  {
    identity: registryIdentity.id
    server: '${registryName}.azurecr.io'
  }
]
var rotationSecrets = [
  {
    name: 'database-url'
    value: databaseUrl
  }
  {
    name: 'blob-connection-string'
    value: blobConnectionString
  }
  {
    name: 'operator-password-hash'
    value: operatorRotationEnabled ? validatedRotationPasswordHash : validatedOperatorPasswordHash
  }
  {
    name: 'session-pepper'
    value: sessionPepper
  }
]
var rotationEnvironment = [
  {
    name: 'BIZPULSE_RUNTIME_ENVIRONMENT'
    value: 'cloud'
  }
  {
    name: 'BIZPULSE_DATABASE_URL'
    secretRef: 'database-url'
  }
  {
    name: 'BIZPULSE_BLOB_ENDPOINT'
    value: 'https://${storageAccount.name}.blob.${az.environment().suffixes.storage}'
  }
  {
    name: 'BIZPULSE_BLOB_CONTAINER'
    value: blobContainer
  }
  {
    name: 'BIZPULSE_BLOB_CONNECTION_STRING'
    secretRef: 'blob-connection-string'
  }
  {
    name: 'BIZPULSE_ALLOWED_ORIGIN'
    value: publicUrl
  }
  {
    name: 'BIZPULSE_OPERATOR_PASSWORD_HASH'
    secretRef: 'operator-password-hash'
  }
  {
    name: 'BIZPULSE_SESSION_PEPPER'
    secretRef: 'session-pepper'
  }
  {
    name: 'BIZPULSE_EXPECTED_OPERATOR_PASSWORD_HASH_SHA256'
    value: validatedRotationExpectedHashFingerprint
  }
  {
    name: 'BIZPULSE_OPERATOR_ROTATION_ID'
    value: validatedRotationId
  }
]
var jobResources = {
  cpu: json('0.5')
  memory: '1Gi'
}

resource operatorRotationJob 'Microsoft.App/jobs@2024-03-01' = {
  name: rotationJobName
  location: location
  tags: tags
  identity: {
    type: 'UserAssigned'
    userAssignedIdentities: {
      '${registryIdentity.id}': {}
    }
  }
  properties: {
    environmentId: environment.id
    configuration: {
      triggerType: 'Manual'
      replicaTimeout: 900
      replicaRetryLimit: 0
      manualTriggerConfig: {
        parallelism: 1
        replicaCompletionCount: 1
      }
      registries: registryConfiguration
      secrets: rotationSecrets
    }
    template: {
      containers: [
        {
          name: 'operator-rotation'
          image: validatedContainerImage
          command: [
            'python'
          ]
          args: [
            'scripts/rotate_operator_password.py'
          ]
          env: rotationEnvironment
          resources: jobResources
        }
      ]
    }
  }
}

output operatorRotationJobName string = operatorRotationJob.name
