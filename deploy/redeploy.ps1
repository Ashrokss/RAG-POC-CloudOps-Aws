# Rebuilds and redeploys streamlit_app.py to the existing Azure App Service.
# Run from the repo root: .\deploy\redeploy.ps1
#
# Packages what streamlit_app.py's import chain reaches (see
# deploy/requirements-deploy.txt's header comment for the dependency
# exclusions) PLUS data/raw_rca_docs/ - easy to assume that's skippable since
# the vectors are already in data/chroma_db/, but keyword/hybrid/hybrid_rerank
# retrieval rebuild BM25 fresh from the raw markdown on every single call
# (rag/retrieval/keyword.py: BM25 has no persisted store the way Chroma does),
# so an empty raw_rca_docs/ means those three strategies fail immediately
# with "not enough values to unpack (expected 3, got 0)" from
# BM25Retriever.from_documents([]) - found by deploying without it first.

$ErrorActionPreference = "Stop"
$pkg = "deploy\package"

Remove-Item -Recurse -Force $pkg -ErrorAction SilentlyContinue
New-Item -ItemType Directory -Path $pkg -Force | Out-Null

Copy-Item streamlit_app.py $pkg\
Copy-Item -Recurse config $pkg\config
Copy-Item -Recurse rag $pkg\rag
Copy-Item -Recurse eval $pkg\eval
New-Item -ItemType Directory -Path "$pkg\data\chroma_db" -Force | Out-Null
Copy-Item -Recurse data\chroma_db\* "$pkg\data\chroma_db\"
New-Item -ItemType Directory -Path "$pkg\data\raw_rca_docs\real" -Force | Out-Null
Copy-Item -Recurse data\raw_rca_docs\real\*.md "$pkg\data\raw_rca_docs\real\"
New-Item -ItemType Directory -Path "$pkg\data\raw_rca_docs\synthetic" -Force | Out-Null
Copy-Item -Recurse data\raw_rca_docs\synthetic\*.md "$pkg\data\raw_rca_docs\synthetic\"
New-Item -ItemType Directory -Path "$pkg\data\golden_qa" -Force | Out-Null
Copy-Item data\golden_qa\golden_qa.yaml "$pkg\data\golden_qa\"
Copy-Item deploy\requirements-deploy.txt "$pkg\requirements.txt"

Get-ChildItem $pkg -Recurse -Directory -Filter "__pycache__" | Remove-Item -Recurse -Force

Compress-Archive -Path "$pkg\*" -DestinationPath "deploy\frontend.zip" -Force

az webapp deploy `
  --name rag-sre-poc-frontend `
  --resource-group rg-rag-poc-frontend `
  --src-path "deploy\frontend.zip" `
  --type zip

Remove-Item -Recurse -Force $pkg, "deploy\frontend.zip"

Write-Host "Deployed. URL: http://rag-sre-poc-frontend.azurewebsites.net"
Write-Host "Health check: (Invoke-WebRequest http://rag-sre-poc-frontend.azurewebsites.net/_stcore/health -UseBasicParsing).Content"
