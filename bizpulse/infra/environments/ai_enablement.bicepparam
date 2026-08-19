using '../ai_enablement.bicep'

// This file is deliberately inert. Exact names, target and the secure value
// belong only to a separately approved, package-bound child process.
param deploymentEnabled = false
param namePrefix = 'needs-ai-auth'
param location = 'requires-authorization'
param logAnalyticsWorkspaceName = 'requires-authorization'
