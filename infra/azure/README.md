# Azure AI infra for this POC

`main.bicep` provisions the Azure AI Services (Cognitive Services) account this POC's
Azure provider (`rag/llm/azure_llm.py`, `rag/embeddings/azure_embeddings.py`) talks to.
By default it does **not** create a new account and does **not** touch the existing chat
deployment - it only adds an embedding-model deployment to the existing
`xecops360-ai-fddwk` account, so `AZURE_AI_EMBED_MODEL` can be set and retrieval stops
running on mock embeddings.

Nothing here has been deployed by the assistant - provisioning is a billed, shared-state
change, so it's left as a deliberate command you run yourself.

## Confirmed environment (read-only checks already run)

- Resource group: **`rg-xecops360-prod`** - this is the real production resource group
  for the whole xecops360 platform (18 other resources live in it: the Cognitive
  Services account itself, a PostgreSQL flexible server, storage accounts, web apps,
  a container registry, a key vault, and more). `main.bicep`'s defaults are built to
  extend it without disturbing any of that.
- Account: `xecops360-ai-fddwk`, kind `AIServices`, region `eastus2`.
- Existing deployments (verified via `az cognitiveservices account deployment list`):
  `gpt-4o` (version `2024-11-20`) and `gpt-4o-mini` (version `2024-07-18`, **capacity
  18**) - both `Running`, both created/modified by real users, i.e. actually in use.
  This is exactly why `manageChatDeployment` defaults to `false`: an earlier draft of
  this template always managed the chat deployment, which would have PUT the
  then-guessed default capacity (10) over the live value (18) the first time anyone
  ran it.
- Embedding model catalog (verified via `az cognitiveservices account list-models`):
  `text-embedding-3-small` (v1), `text-embedding-3-large` (v1), `text-embedding-ada-002`
  (v2), plus two Cohere embedding models - `main.bicep`'s default
  (`text-embedding-3-small`) is confirmed available on this account.
- **`az deployment group what-if` was run against the real resource group with the
  default parameters** (see `prod.bicepparam`) and confirmed the only change is
  `+ Create` on the new `text-embedding-3-small` deployment - all 18 other resources,
  including the account and its existing chat deployments, show `* Ignore` (no change).

## 1. Plan (preview, no changes made)

Always run this before apply - it's the Bicep/ARM equivalent of `terraform plan`, and
it's what produced the "confirmed environment" facts above:

```powershell
az deployment group what-if --resource-group rg-xecops360-prod --parameters infra/azure/prod.bicepparam --template-file infra/azure/main.bicep
```

Expected output against the pinned parameter file: `+ Create` on
`Microsoft.CognitiveServices/accounts/xecops360-ai-fddwk/deployments/text-embedding-3-small`
only, `* Ignore` on all 18 other resources in the resource group (including the account
itself and its existing chat deployments). If your plan output differs from that -
anything else marked `+`/`~`/`-`, or a different resource count - stop and re-read the
diff before applying; something in the environment has drifted from what's documented
here.

## 2. Apply

Only after the plan output matches what's expected above:

```powershell
az deployment group create --resource-group rg-xecops360-prod --parameters infra/azure/prod.bicepparam --template-file infra/azure/main.bicep
```

To also wire up the AD role assignment for the `AZURE_CLIENT_ID` service principal
(unused by the app today, reserved for a future token-auth path - see `main.bicep`),
get its **object ID** first, not its client/application ID, they are different GUIDs.
Plan, then apply, same pattern as above:

```powershell
az ad sp show --id $env:AZURE_CLIENT_ID --query id -o tsv
az deployment group what-if --resource-group rg-xecops360-prod --parameters infra/azure/prod.bicepparam servicePrincipalObjectId=<object-id> --template-file infra/azure/main.bicep
az deployment group create --resource-group rg-xecops360-prod --parameters infra/azure/prod.bicepparam servicePrincipalObjectId=<object-id> --template-file infra/azure/main.bicep
```

The template assigns the built-in "Cognitive Services User" role
(`a97b65f3-24c7-4388-baec-2e87135dc908`) - confirm that GUID still matches before
relying on it: `az role definition list --name "Cognitive Services User" --query "[0].name" -o tsv`.

To stand up a **separate** account instead (a different environment, or the eventual
CloudOps-AWS integration) rather than extending `rg-xecops360-prod`'s account, override
the relevant parameters directly instead of using `prod.bicepparam` - plan first, since
this path hasn't been what-if'd against a real resource group the way the default path
above has:

```powershell
az deployment group what-if `
  --resource-group <new-or-existing-rg> `
  --template-file infra/azure/main.bicep `
  --parameters createNewAccount=true manageChatDeployment=true aiServicesName=<new-account-name> location=eastus2

az deployment group create `
  --resource-group <new-or-existing-rg> `
  --template-file infra/azure/main.bicep `
  --parameters createNewAccount=true manageChatDeployment=true aiServicesName=<new-account-name> location=eastus2
```

If Azure's current API surface has moved past what this file assumes (author-time
values, may have drifted by the time you run this), re-check before deploying:

```powershell
az provider show -n Microsoft.CognitiveServices --query "resourceTypes[?resourceType=='accounts'].apiVersions[0]" -o tsv
```

## After it deploys

Fetch the key with a command, not from a deployment output (outputs land in deployment
history in plaintext - `main.bicep` deliberately doesn't emit one):

```powershell
az cognitiveservices account keys list --name xecops360-ai-fddwk --resource-group rg-xecops360-prod --query key1 -o tsv
```

Then update `.env` (never `.env.example`) - `AZURE_AI_ENDPOINT`/`AZURE_AI_KEY` don't
change, since the account itself didn't change:

```
AZURE_AI_EMBED_MODEL=text-embedding-3-small
```

Confirm retrieval is live:

```powershell
python -c "from config.settings import get_settings; print(get_settings().mock_mode)"
python -m cli.ingest run --reset
python -m cli.query ask "What was the root cause of INC-2025-0101?" --strategy semantic
```

A `False` mock_mode plus `cli.ingest run --reset` completing with no "AZURE_AI_EMBED_MODEL
is not set" warning on stderr confirms embeddings are live too.
