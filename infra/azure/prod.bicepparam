using 'main.bicep'

// Pinned to the confirmed rg-xecops360-prod environment (verified via
// `az cognitiveservices account show` / `az deployment group what-if` - see
// infra/azure/README.md). Deploy with:
//   az deployment group create --resource-group rg-xecops360-prod --parameters infra/azure/prod.bicepparam

param aiServicesName = 'xecops360-ai-fddwk'
param createNewAccount = false
param manageChatDeployment = false

param deployEmbeddingModel = true
param embeddingDeploymentName = 'text-embedding-3-small'
param embeddingModelName = 'text-embedding-3-small'
param embeddingModelVersion = '1'
param embeddingCapacity = 30
