using '../ai_secret_write.bicep'

// Deliberately inert. The approved runner supplies the secure value over the
// child process stdin; no real value belongs in this file or process argv.
param deploymentEnabled = false
param vaultName = 'needs-authorization'
param openAiApiKey = readEnvironmentVariable('BIZPULSE_DEPLOY_OPENAI_API_KEY', '')
