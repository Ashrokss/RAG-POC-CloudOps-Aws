# Streamlit frontend hosting

**Live URL: http://rag-sre-poc-frontend.azurewebsites.net**

Deployed to Azure App Service (F1 free tier, Linux, Python 3.11) in a dedicated
resource group `rg-rag-poc-frontend` (region `centralus` - `eastus2` had zero
available App Service VM quota on this subscription, already consumed by
`rg-xecops360-prod`'s existing plans). Kept in its own resource group,
separate from `rg-xecops360-prod`, so it can be torn down independently
without touching any production infrastructure.

## What's running

`streamlit_app.py` calls `rag.chain.rag_chain` directly (no FastAPI layer) against:

- **Live Azure AI** - the same `xecops360-ai-fddwk` account used everywhere else
  in this project (`gpt-4o-mini` chat, `text-embedding-3-small` embeddings).
- **A pre-built Chroma index** shipped as part of the deployment package
  (`data/chroma_db/`, ~4MB) - the deployed app never re-runs ingestion into
  Chroma, it only ever reads the index that was already built locally.
- **The raw RCA markdown** (`data/raw_rca_docs/`) - also shipped, and NOT
  optional despite the Chroma index being pre-built: `keyword`/`hybrid`/
  `hybrid_rerank` retrieval all rebuild BM25 fresh from these files on every
  call (BM25 has no persisted store the way Chroma does - see
  `rag/retrieval/keyword.py`). Deploying without this folder isn't a
  degraded mode, it's a hard failure for 3 of the 4 strategies (found the
  hard way - see git history on `deploy/redeploy.ps1`).

## Known limitations (accepted trade-offs of F1 free tier + "fully open" mode)

- **No authentication.** Anyone with the URL can trigger real, billed Azure AI
  calls against `rg-xecops360-prod`'s account. This was an explicit choice
  (see conversation) over adding a password gate - revisit if abuse or cost
  becomes a problem.
- **No "Always On."** Not available below Basic tier - the app idles after ~20
  minutes of inactivity and cold-starts (extra latency, occasionally a failed
  first request) on the next visit.
- **60 CPU-minutes/day, 165MB/day outbound transfer, 1GB storage** - F1 tier
  caps. A single heavy test session could plausibly exhaust the daily CPU
  quota; if the app stops responding until the following day, this is why.
- **Secrets are in App Service Application Settings**, not a Key Vault -
  reasonable for a POC, not for anything longer-lived. `AZURE_TENANT_ID`/
  `AZURE_CLIENT_ID`/`AZURE_CLIENT_SECRET` were deliberately left OUT of the
  app settings (unused by any code path - see `config/settings.py`), so the
  AD service-principal secret isn't exposed here at all.

## Redeploying after a code/corpus change

```powershell
.\deploy\redeploy.ps1
```

This rebuilds the same package `deploy/requirements-deploy.txt` describes
(trimmed to what `streamlit_app.py` actually imports - no boto3/pytest/
typer/fastapi) and re-zip-deploys it.

**Verify by actually using the app in a browser and trying all four
strategies, not just by checking `/_stcore/health`.** That endpoint only
confirms Streamlit's server process is alive - it does NOT run
`streamlit_app.py`'s own script. Script execution (and any exception in it)
only happens per-session, when a real browser opens the WebSocket connection
`/_stcore/health` never establishes. Two real bugs shipped past every
automated check available here (health endpoint green, container logs clean,
local Windows tests passing) and were only caught by opening the URL and
clicking "Ask":
1. Old system sqlite3 on the Debian base image (fixed via `pysqlite3-binary`,
   see `rag/vectorstore/chroma_store.py`).
2. Missing `data/raw_rca_docs/` breaking 3 of 4 retrieval strategies (see
   above).

If you don't have a browser handy, the closest thing to a real check is
Streamlit's own `AppTest` harness run against a full round-trip (see how this
was verified locally before the first deploy) - still not a substitute for
an actual click-through post-deploy.

## Tearing down

```powershell
az group delete --name rg-rag-poc-frontend --yes
```

Deletes the web app and its App Service plan in one step; does not touch
`rg-xecops360-prod` or the Azure AI account.
