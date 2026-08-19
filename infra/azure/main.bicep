// Provisions (or extends) the Azure AI Foundry / Cognitive Services multi-service
// account this POC's Azure provider talks to (rag/llm/azure_llm.py,
// rag/embeddings/azure_embeddings.py). Defaults target the account already in use
// (xecops360-ai-fddwk, confirmed live in resource group rg-xecops360-prod, region
// eastus2) and by default only ADD an embedding deployment to it - the account
// already has gpt-4o and gpt-4o-mini deployments in production use (verified via
// `az cognitiveservices account deployment list`), so manageChatDeployment defaults
// to false specifically so this template can never overwrite that live deployment's
// capacity/version. Set createNewAccount=true to stand up a fresh account instead
// (e.g. for a separate environment or the eventual CloudOps-AWS integration) - pair
// it with manageChatDeployment=true, since a fresh account has no chat deployment yet.
//
// `parent:`/`scope:` only accept a direct resource reference, not a ternary
// between two conditionally-declared resources (Bicep errors BCP240/BCP420) - so
// the child resources below always point `parent:`/`scope:` at the single
// `aiServices existing` reference, and separately carry a conditional `dependsOn`
// on `newAiServices` for when createNewAccount=true. `existing` only produces a
// resource-ID reference at compile time; ARM doesn't require the resource to
// already exist until the dependent deployment actually runs, which the explicit
// dependsOn orders correctly.
//
// API version note: 2024-10-01 was current at authoring time (this file predates a
// verified check against Azure's Aug 2026 API surface). Run
// `az provider show -n Microsoft.CognitiveServices --query "resourceTypes[?resourceType=='accounts'].apiVersions[0]"`
// before deploying and bump the apiVersion below if a newer one is GA.

@description('Name of the Azure AI Services (Cognitive Services) account to use or create.')
param aiServicesName string = 'xecops360-ai-fddwk'

@description('Azure region. Only used when createNewAccount=true - ignored for an existing account.')
param location string = resourceGroup().location

@description('true = create a new AI Services account. false (default) = extend the existing one named above with the deployments below.')
param createNewAccount bool = false

@description('Create/update the chat deployment. Defaults to false: rg-xecops360-prod already has a live gpt-4o-mini deployment (capacity 18, verified via az cognitiveservices account deployment list) that this template must not silently overwrite. Set true only when standing up a fresh account (createNewAccount=true) that has no chat deployment yet.')
param manageChatDeployment bool = false
@description('Chat deployment name - must match AZURE_AI_CHAT_MODEL / OPENAI_MODEL in .env.')
param chatDeploymentName string = 'gpt-4o-mini'
@description('Chat model name in the Azure AI model catalog.')
param chatModelName string = 'gpt-4o-mini'
@description('Chat model version. Verify against the model catalog - version strings change over time. 2024-07-18 matches the version already live on xecops360-ai-fddwk.')
param chatModelVersion string = '2024-07-18'
@description('Chat deployment capacity, in units of 1,000 tokens/minute. 18 matches the capacity already live on xecops360-ai-fddwk - do not lower this if manageChatDeployment=true against that account, or the live deployment gets throttled down.')
param chatCapacity int = 18

@description('Deploy an embedding model alongside the chat model. Set false if you only want the chat deployment.')
param deployEmbeddingModel bool = true
@description('Embedding deployment name - set this same value as AZURE_AI_EMBED_MODEL in .env once deployed.')
param embeddingDeploymentName string = 'text-embedding-3-small'
@description('Embedding model name in the Azure AI model catalog.')
param embeddingModelName string = 'text-embedding-3-small'
@description('Embedding model version. Verify against the model catalog - version strings change over time.')
param embeddingModelVersion string = '1'
@description('Embedding deployment capacity, in units of 1,000 tokens/minute.')
param embeddingCapacity int = 30

@description('SKU applied to both model deployments.')
param deploymentSkuName string = 'GlobalStandard'

@description('Object ID (not client/application ID - see infra/azure/README.md) of the AZURE_CLIENT_ID service principal. Leave blank to skip the role assignment.')
param servicePrincipalObjectId string = ''

resource aiServices 'Microsoft.CognitiveServices/accounts@2024-10-01' existing = {
  name: aiServicesName
}

resource newAiServices 'Microsoft.CognitiveServices/accounts@2024-10-01' = if (createNewAccount) {
  name: aiServicesName
  location: location
  kind: 'AIServices'
  sku: {
    name: 'S0'
  }
  identity: {
    type: 'SystemAssigned'
  }
  properties: {
    customSubDomainName: aiServicesName
    publicNetworkAccess: 'Enabled'
    // Key auth stays enabled because rag/llm/azure_llm.py and
    // rag/embeddings/azure_embeddings.py currently authenticate with
    // AzureKeyCredential, not an AAD token - flip this only after that code
    // path is migrated to token-based auth.
    disableLocalAuth: false
  }
}

resource embeddingDeployment 'Microsoft.CognitiveServices/accounts/deployments@2024-10-01' = if (deployEmbeddingModel) {
  parent: aiServices
  name: embeddingDeploymentName
  sku: {
    name: deploymentSkuName
    capacity: embeddingCapacity
  }
  properties: {
    model: {
      format: 'OpenAI'
      name: embeddingModelName
      version: embeddingModelVersion
    }
  }
  // aiServices is an `existing` reference, so it carries no automatic
  // dependency on newAiServices - this dependsOn is the only thing that
  // orders account creation before this deployment when createNewAccount=true.
  dependsOn: createNewAccount ? [newAiServices] : []
}

resource chatDeployment 'Microsoft.CognitiveServices/accounts/deployments@2024-10-01' = if (manageChatDeployment) {
  parent: aiServices
  name: chatDeploymentName
  sku: {
    name: deploymentSkuName
    capacity: chatCapacity
  }
  properties: {
    model: {
      format: 'OpenAI'
      name: chatModelName
      version: chatModelVersion
    }
  }
  // Serialized after the embedding deployment (or the account, if there's no
  // embedding deployment to chain after) rather than left to run in parallel,
  // because concurrent PUTs of two deployments under the same Cognitive
  // Services account are a known source of ARM conflict errors.
  dependsOn: deployEmbeddingModel ? [embeddingDeployment] : (createNewAccount ? [newAiServices] : [])
}

resource servicePrincipalRoleAssignment 'Microsoft.Authorization/roleAssignments@2022-04-01' = if (!empty(servicePrincipalObjectId)) {
  name: guid(aiServicesName, servicePrincipalObjectId, 'CognitiveServicesUser')
  scope: aiServices
  properties: {
    // "Cognitive Services User" is enough to call inference endpoints; it
    // deliberately does NOT grant account-management permissions. Unused by
    // the app today (see the disableLocalAuth comment above) - it exists so
    // AZURE_TENANT_ID/CLIENT_ID's AD path is ready to use without a second
    // infra change if key auth is ever retired.
    roleDefinitionId: subscriptionResourceId('Microsoft.Authorization/roleDefinitions', 'a97b65f3-24c7-4388-baec-2e87135dc908')
    principalId: servicePrincipalObjectId
    principalType: 'ServicePrincipal'
  }
  dependsOn: createNewAccount ? [newAiServices] : []
}

// customSubDomainName is set to aiServicesName on a freshly created account, so
// this string form is exact for both branches - reading newAiServices.properties.endpoint
// instead would need a conditional access Bicep can't prove non-null at compile time.
output aiServicesEndpoint string = 'https://${aiServicesName}.cognitiveservices.azure.com/'
output chatDeploymentName string = chatDeploymentName
output embeddingDeploymentName string = deployEmbeddingModel ? embeddingDeploymentName : ''
// Deliberately no key output - ARM/Bicep outputs land in deployment history
// and CLI/portal logs in plaintext. Fetch the key with the az command in
// infra/azure/README.md instead of reading it from a deployment output.
