metadata description = 'Phased Container Apps environment with private preparation and maintenance jobs.'

param location string
param namePrefix string
param containerImage string
@minLength(64)
@maxLength(64)
param syntheticManifestSha256 string
@minLength(36)
@maxLength(36)
param syntheticDatasetVersionId string
@maxLength(32)
param revisionSuffix string
param applicationEnabled bool
param operatorRotationEnabled bool
@secure()
param operatorRotationPasswordHash string
param operatorRotationExpectedHashFingerprint string
param operatorRotationId string
param appSubnetId string
param logAnalyticsCustomerId string
param logAnalyticsWorkspaceName string
param applicationInsightsConnectionString string
param registryServer string
param registryIdentityResourceId string
@secure()
param databaseUrl string
param blobEndpoint string
param blobContainer string
param storageAccountName string
@secure()
param operatorPasswordHash string
@secure()
param sessionPepper string
param openaiKeyVaultUrl string
param openaiManagedIdentityClientId string
param openaiManagedIdentityResourceId string
param aiChatEnabled bool
param aiBudgetFailureRehearsal bool
param aiDailyAttemptLimit int
param aiMonthlyTokenLimit int
param aiMaxConcurrentTurns int
param aiSessionAttemptLimitPerMinute int
param aiGlobalAttemptLimitPerMinute int
param demoSessionRateLimitPerHour int
param tags object

resource logWorkspace 'Microsoft.OperationalInsights/workspaces@2023-09-01' existing = {
  name: logAnalyticsWorkspaceName
}

resource storageAccount 'Microsoft.Storage/storageAccounts@2023-05-01' existing = {
  name: storageAccountName
}

var logAnalyticsSharedKey = logWorkspace.listKeys().primarySharedKey
var storageAccountKey = storageAccount.listKeys().keys[0].value
var blobConnectionString = 'DefaultEndpointsProtocol=https;AccountName=${storageAccount.name};AccountKey=${storageAccountKey};EndpointSuffix=${az.environment().suffixes.storage}'

resource environment 'Microsoft.App/managedEnvironments@2024-03-01' = {
  name: take('${namePrefix}-env', 60)
  location: location
  tags: tags
  properties: {
    appLogsConfiguration: {
      destination: 'log-analytics'
      logAnalyticsConfiguration: {
        customerId: logAnalyticsCustomerId
        sharedKey: logAnalyticsSharedKey
      }
    }
    vnetConfiguration: {
      infrastructureSubnetId: appSubnetId
      internal: false
    }
  }
}

var appName = take('${namePrefix}-app', 32)
var publicUrl = 'https://${appName}.${environment.properties.defaultDomain}'
var registryConfiguration = [
  {
    identity: registryIdentityResourceId
    server: registryServer
  }
]
var jobSecrets = [
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
    value: operatorPasswordHash
  }
  {
    name: 'session-pepper'
    value: sessionPepper
  }
]
var operatorRotationJobSecrets = [
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
    value: operatorRotationEnabled ? operatorRotationPasswordHash : operatorPasswordHash
  }
  {
    name: 'session-pepper'
    value: sessionPepper
  }
]
var jobEnvironment = [
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
    value: blobEndpoint
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
]
var operatorRotationJobEnvironment = [
  ...jobEnvironment
  {
    name: 'BIZPULSE_EXPECTED_OPERATOR_PASSWORD_HASH_SHA256'
    value: operatorRotationEnabled ? operatorRotationExpectedHashFingerprint : ''
  }
  {
    name: 'BIZPULSE_OPERATOR_ROTATION_ID'
    value: operatorRotationEnabled ? operatorRotationId : ''
  }
]
var jobResources = {
  cpu: json('0.5')
  memory: '1Gi'
}
var phase1AppEnvironment = [
  {
    name: 'BIZPULSE_RUNTIME_ENVIRONMENT'
    value: 'phase1-fenced'
  }
]
var phase2AppEnvironment = [
  ...jobEnvironment
  ...(aiChatEnabled ? [
    {
      name: 'BIZPULSE_OPENAI_KEY_VAULT_URL'
      value: openaiKeyVaultUrl
    }
    {
      name: 'BIZPULSE_OPENAI_KEY_VAULT_SECRET_NAME'
      value: 'openai-api-key'
    }
    {
      name: 'BIZPULSE_OPENAI_MANAGED_IDENTITY_CLIENT_ID'
      value: openaiManagedIdentityClientId
    }
  ] : [])
  {
    name: 'BIZPULSE_AI_CHAT_ENABLED'
    value: aiChatEnabled ? 'true' : 'false'
  }
  ...(aiBudgetFailureRehearsal ? [
    {
      name: 'BIZPULSE_AI_BUDGET_FAILURE_REHEARSAL'
      value: 'true'
    }
  ] : [])
  {
    name: 'BIZPULSE_AI_DAILY_ATTEMPT_LIMIT'
    value: string(aiDailyAttemptLimit)
  }
  {
    name: 'BIZPULSE_AI_MONTHLY_TOKEN_LIMIT'
    value: string(aiMonthlyTokenLimit)
  }
  {
    name: 'BIZPULSE_AI_MAX_CONCURRENT_TURNS'
    value: string(aiMaxConcurrentTurns)
  }
  {
    name: 'BIZPULSE_AI_SESSION_ATTEMPT_LIMIT_PER_MINUTE'
    value: string(aiSessionAttemptLimitPerMinute)
  }
  {
    name: 'BIZPULSE_AI_GLOBAL_ATTEMPT_LIMIT_PER_MINUTE'
    value: string(aiGlobalAttemptLimitPerMinute)
  }
  {
    name: 'BIZPULSE_DEMO_SESSION_RATE_LIMIT_PER_HOUR'
    value: string(demoSessionRateLimitPerHour)
  }
  {
    name: 'BIZPULSE_OPENAI_MODEL'
    value: 'gpt-5.4-nano-2026-03-17'
  }
  {
    name: 'BIZPULSE_OPENAI_REASONING_EFFORT'
    value: 'low'
  }
  {
    name: 'APPLICATIONINSIGHTS_CONNECTION_STRING'
    value: applicationInsightsConnectionString
  }
]
var appSecrets = applicationEnabled ? jobSecrets : []
var appProbes = [
  {
    type: 'Liveness'
    httpGet: {
      path: '/health/live'
      port: 8000
      scheme: 'HTTP'
    }
    initialDelaySeconds: 15
    periodSeconds: 30
    timeoutSeconds: 5
    failureThreshold: 3
  }
  {
    type: 'Readiness'
    httpGet: {
      path: '/health/ready'
      port: 8000
      scheme: 'HTTP'
    }
    initialDelaySeconds: 10
    periodSeconds: 10
    timeoutSeconds: 5
    failureThreshold: 3
  }
]
var appContainer = union({
  name: 'bizpulse'
  image: containerImage
  env: applicationEnabled ? phase2AppEnvironment : phase1AppEnvironment
  probes: appProbes
  resources: jobResources
}, applicationEnabled ? {} : {
  command: [
    'python'
  ]
  args: [
    'scripts/phase1_fence_server.py'
  ]
})
var appUserAssignedIdentities = union(
  {
    '${registryIdentityResourceId}': {}
  },
  aiChatEnabled ? {
    '${openaiManagedIdentityResourceId}': {}
  } : {}
)

resource migrationJob 'Microsoft.App/jobs@2024-03-01' = {
  name: take('${namePrefix}-prepare', 32)
  location: location
  tags: tags
  identity: {
    type: 'UserAssigned'
    userAssignedIdentities: {
      '${registryIdentityResourceId}': {}
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
      secrets: jobSecrets
    }
    template: {
      containers: [
        {
          name: 'prepare'
          image: containerImage
          command: [
            'python'
          ]
          args: [
            'scripts/prepare_cloud.py'
          ]
          env: jobEnvironment
          resources: jobResources
        }
      ]
    }
  }
}

resource seedJob 'Microsoft.App/jobs@2024-03-01' = {
  name: take('${namePrefix}-seed', 32)
  location: location
  tags: tags
  identity: {
    type: 'UserAssigned'
    userAssignedIdentities: {
      '${registryIdentityResourceId}': {}
    }
  }
  properties: {
    environmentId: environment.id
    configuration: {
      triggerType: 'Manual'
      replicaTimeout: 1800
      replicaRetryLimit: 0
      manualTriggerConfig: {
        parallelism: 1
        replicaCompletionCount: 1
      }
      registries: registryConfiguration
      secrets: jobSecrets
    }
    template: {
      containers: [
        {
          name: 'seed'
          image: containerImage
          command: [
            'python'
          ]
          args: [
            'scripts/seed_demo.py'
            'tests/fixtures/synthetic/v1'
            '--expected-manifest-sha256'
            syntheticManifestSha256
            '--expected-dataset-version-id'
            syntheticDatasetVersionId
          ]
          env: jobEnvironment
          resources: jobResources
        }
      ]
    }
  }
}

resource sessionMaintenanceJob 'Microsoft.App/jobs@2024-03-01' = {
  name: take('${namePrefix}-sessions', 32)
  location: location
  tags: tags
  identity: {
    type: 'UserAssigned'
    userAssignedIdentities: {
      '${registryIdentityResourceId}': {}
    }
  }
  properties: {
    environmentId: environment.id
    configuration: union({
      replicaTimeout: 300
      replicaRetryLimit: 0
      registries: registryConfiguration
      secrets: jobSecrets
    }, applicationEnabled ? {
      triggerType: 'Schedule'
      scheduleTriggerConfig: {
        cronExpression: '*/15 * * * *'
        parallelism: 1
        replicaCompletionCount: 1
      }
    } : {
      triggerType: 'Manual'
      manualTriggerConfig: {
        parallelism: 1
        replicaCompletionCount: 1
      }
    })
    template: {
      containers: [
        {
          name: 'maintain-sessions'
          image: containerImage
          command: [
            'python'
          ]
          args: [
            'scripts/maintain_sessions.py'
          ]
          env: jobEnvironment
          resources: jobResources
        }
      ]
    }
  }
}

resource storageMaintenanceJob 'Microsoft.App/jobs@2024-03-01' = {
  name: take('${namePrefix}-storage', 32)
  location: location
  tags: tags
  identity: {
    type: 'UserAssigned'
    userAssignedIdentities: {
      '${registryIdentityResourceId}': {}
    }
  }
  properties: {
    environmentId: environment.id
    configuration: union({
      replicaTimeout: 600
      replicaRetryLimit: 0
      registries: registryConfiguration
      secrets: jobSecrets
    }, applicationEnabled ? {
      triggerType: 'Schedule'
      scheduleTriggerConfig: {
        cronExpression: '0 * * * *'
        parallelism: 1
        replicaCompletionCount: 1
      }
    } : {
      triggerType: 'Manual'
      manualTriggerConfig: {
        parallelism: 1
        replicaCompletionCount: 1
      }
    })
    template: {
      containers: [
        {
          name: 'maintain-storage'
          image: containerImage
          command: [
            'python'
          ]
          args: [
            'scripts/maintain_storage.py'
            '--expire-temporary'
          ]
          env: jobEnvironment
          resources: jobResources
        }
      ]
    }
  }
}

resource operatorRotationJob 'Microsoft.App/jobs@2024-03-01' = {
  name: take('${namePrefix}-rotate-operator', 32)
  location: location
  tags: tags
  identity: {
    type: 'UserAssigned'
    userAssignedIdentities: {
      '${registryIdentityResourceId}': {}
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
      secrets: operatorRotationJobSecrets
    }
    template: {
      containers: [
        {
          name: 'operator-rotation'
          image: containerImage
          command: [
            'python'
          ]
          args: [
            'scripts/rotate_operator_password.py'
          ]
          env: operatorRotationJobEnvironment
          resources: jobResources
        }
      ]
    }
  }
}

resource app 'Microsoft.App/containerApps@2024-03-01' = {
  name: appName
  location: location
  tags: tags
  identity: {
    type: 'UserAssigned'
    userAssignedIdentities: appUserAssignedIdentities
  }
  properties: {
    environmentId: environment.id
    configuration: {
      activeRevisionsMode: 'Single'
      ingress: {
        allowInsecure: false
        external: applicationEnabled
        targetPort: 8000
        traffic: [
          {
            latestRevision: true
            weight: 100
          }
        ]
        transport: 'auto'
      }
      registries: registryConfiguration
      secrets: appSecrets
    }
    template: {
      revisionSuffix: revisionSuffix
      containers: [
        appContainer
      ]
      scale: {
        minReplicas: applicationEnabled ? 1 : 0
        maxReplicas: 1
      }
    }
  }
}

output appId string = app.id
output publicUrl string = applicationEnabled ? publicUrl : ''
output revisionName string = '${appName}--${revisionSuffix}'
output migrationJobName string = migrationJob.name
output seedJobName string = seedJob.name
output operatorRotationJobName string = operatorRotationJob.name
output sessionMaintenanceJobName string = sessionMaintenanceJob.name
output storageMaintenanceJobName string = storageMaintenanceJob.name
