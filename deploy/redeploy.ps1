# Rebuilds and redeploys the Streamlit multipage app (streamlit_app.py +
# pages/2_RCA_Platform_v2.py) to the existing Azure App Service.
# Run from the repo root: .\deploy\redeploy.ps1
#
# NOTE: chunk ids are now derived from (doc_id, section, ordinal), so a
# data/chroma_db/ built before that change carries stale ids. Re-run
# `python -m cli.ingest run --reset` locally before deploying, or the shipped
# index and the in-memory chunk list will disagree about what a chunk is.
# Likewise, data/rca.db must be rebuilt against the same embedder the deployed
# app queries with (`python -m rca.cli ingest --reset` with real Azure
# credentials loaded) - rca/store.py refuses to serve a mismatched embedder.
#
# Packages what streamlit_app.py's AND pages/2_RCA_Platform_v2.py's import
# chains reach (see deploy/requirements-deploy.txt's header comment for the
# dependency exclusions) PLUS data/raw_rca_docs/ - easy to assume that's
# skippable since the vectors are already in data/chroma_db/, but
# keyword/hybrid/hybrid_rerank retrieval rebuild BM25 fresh from the raw
# markdown on every single call (rag/retrieval/keyword.py: BM25 has no
# persisted store the way Chroma does), so an empty raw_rca_docs/ means those
# three strategies fail immediately with "not enough values to unpack
# (expected 3, got 0)" from BM25Retriever.from_documents([]) - found by
# deploying without it first.
#
# pages/, rca/, knowledge/ and data/rca.db were previously shipped by hand
# outside this script (that's how RCA Platform v2 went live without this file
# ever being updated to match) - folded in here so redeploying from this
# script no longer silently drops the second page.

$ErrorActionPreference = "Stop"
$pkg = "deploy\package"

Remove-Item -Recurse -Force $pkg -ErrorAction SilentlyContinue
New-Item -ItemType Directory -Path $pkg -Force | Out-Null

Copy-Item streamlit_app.py $pkg\
Copy-Item -Recurse pages $pkg\pages
Copy-Item -Recurse config $pkg\config
Copy-Item -Recurse rag $pkg\rag
Copy-Item -Recurse eval $pkg\eval
Copy-Item -Recurse rca $pkg\rca
# okf/ is the curated service vocabulary the rag/ loader normalises against
# (rag/ingestion/loader.py resolves it relative to rag/, not to cwd), AND (as
# of the known_pattern route) the failure-mode/playbook content
# rca/failure_pattern.py reads directly. Ship it or every services value
# stays unnormalised on rag/'s aggregate route, and rca/'s known_pattern route
# has nothing to match against.
Copy-Item -Recurse okf $pkg\okf
# knowledge/services/*.md is rca/vocabulary.py's service-alias concept layer -
# its rca/ equivalent of okf/services/*.md above.
Copy-Item -Recurse knowledge $pkg\knowledge
New-Item -ItemType Directory -Path "$pkg\data\chroma_db" -Force | Out-Null
Copy-Item -Recurse data\chroma_db\* "$pkg\data\chroma_db\"
New-Item -ItemType Directory -Path "$pkg\data\raw_rca_docs\real" -Force | Out-Null
Copy-Item -Recurse data\raw_rca_docs\real\*.md "$pkg\data\raw_rca_docs\real\"
New-Item -ItemType Directory -Path "$pkg\data\raw_rca_docs\synthetic" -Force | Out-Null
Copy-Item -Recurse data\raw_rca_docs\synthetic\*.md "$pkg\data\raw_rca_docs\synthetic\"
New-Item -ItemType Directory -Path "$pkg\data\golden_qa" -Force | Out-Null
Copy-Item data\golden_qa\golden_qa.yaml "$pkg\data\golden_qa\"
# rca/'s SQLite store - pre-built locally against the same embedder the app
# queries with, the same reason data/chroma_db/ above is pre-built rather than
# ingested on the server.
Copy-Item data\rca.db "$pkg\data\rca.db"
Copy-Item deploy\requirements-deploy.txt "$pkg\requirements.txt"

Get-ChildItem $pkg -Recurse -Directory -Filter "__pycache__" | Remove-Item -Recurse -Force

Compress-Archive -Path "$pkg\*" -DestinationPath "deploy\frontend.zip" -Force

az webapp deploy `
  --name rag-sre-poc-frontend `
  --resource-group rg-rag-poc-frontend `
  --src-path "deploy\frontend.zip" `
  --type zip

Remove-Item -Recurse -Force $pkg, "deploy\frontend.zip"

Write-Host "Deployed. Test Console:      http://rag-sre-poc-frontend.azurewebsites.net"
Write-Host "          RCA Platform v2:   http://rag-sre-poc-frontend.azurewebsites.net/RCA_Platform_v2"
Write-Host "Health check: (Invoke-WebRequest http://rag-sre-poc-frontend.azurewebsites.net/_stcore/health -UseBasicParsing).Content"
