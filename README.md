# RAG-POC-CloudOps-Aws

A proof-of-concept Retrieval-Augmented Generation agent for AWS SRE workflows: it ingests AWS
incident RCA (root-cause-analysis) markdown docs into ChromaDB and answers natural-language
questions about them via an LLM, comparing four retrieval strategies (semantic, keyword, hybrid,
hybrid+rerank) side by side. Two LLM/embedding providers are supported behind one switch -
**Azure AI (default)** and **AWS Bedrock** - see `docs/architecture.md`.

**Runs fully in mock mode with zero cloud credentials.** Ingestion, retrieval, and answering all
work end-to-end against deterministic fake LLM/embedding implementations until real credentials
are supplied for whichever provider is active.

## Setup

```bash
python -m venv .venv
# Windows: .venv\Scripts\activate | macOS/Linux: source .venv/bin/activate
pip install -r requirements.txt
cp .env.example .env
```

## Quick start

```bash
# Ingest RCA docs from data/raw_rca_docs/ into the local Chroma collection
python -m cli.ingest run --reset

# Ask a question using a chosen retrieval strategy
python -m cli.query ask "<question>" --strategy hybrid

# Run the retrieval-strategy comparison over the golden question set
python -m cli.eval run
```

All three commands work out of the box with no cloud credentials - mock mode is auto-detected per
provider.

> **Eval numbers produced before T1 are void.** Until the k cap landed,
> `hybrid` returned up to 2k documents while every other strategy returned k,
> so it answered from double the context and was structurally penalised on
> precision at the same time. Any `reports/` output predating
> `eval_comparison_t1-t5-baseline` compares strategies on unequal footing -
> regenerate rather than cite it.

**Verified state**: 87/87 pytest tests pass (offline, both providers' mock modes forced regardless
of what's in `.env`); `ingest run --reset` indexes 25 RCA docs (20 synthetic + 5 real) into 233
Chroma chunks; `query ask` and `eval run` both work across all four strategies, in both mock mode
and against a real live Azure `gpt-4o-mini` deployment (chat generation and the LLM-judge's
structured-output/tool-calling path were both confirmed working end-to-end against real
credentials; embeddings remain mock - see "Going live" below). Example, live:

```
$ python -m cli.query ask "What was the root cause of INC-2025-0101?" --strategy hybrid
The root cause of INC-2025-0101 was database connection-count scaling, with nothing capping it
below the database's hard limit [INC-2025-0101 · Root Cause].

Citations (1):
  [INC-2025-0101 · Root Cause] database connection-count scaling, with nothing capping it below
  the database's hard limit. The push notification was the trigger, not the root cause;
```

`eval run` scores two question sets in one invocation and reports them separately: the 86 golden
questions (`data/golden_qa/golden_qa.yaml`, scored on retrieval metrics plus token overlap) and the
13 adversarial ones (`data/golden_qa/adversarial_qa.yaml`, scored on refusal correctness, required
incident-id recall, forbidden-id leakage and grounding violations). It writes
`reports/eval_comparison_<run_label>.{md,csv}`. Run one set with `--sets golden` / `--sets
adversarial`.

The adversarial set exists because the golden set contains zero unanswerable questions, zero
aggregates and zero refusal traps - a system that never refuses and never counts scores well on all
86. Its scoring catches things token overlap cannot: a right incident with a wrong date, or the
same cost figure counted twice into a total that appears nowhere in the corpus (`eval/grounding.py`).

Questions asking to count, rank, enumerate or total are routed off the vector index entirely
(`rag/routing/`): top-k retrieval only ever sees k chunks, so "which incident had the longest
detection gap" is not something a better reranker fixes. The aggregate route hands the model the
complete incident index - every incident (or every one matching the services the question named),
with date, severity, status, detection gap, duration and cost - alongside retrieved chunk text, so
the answer is still citable. `RAGAnswer.route` records which path ran, and the Streamlit console
shows it. In mock mode, the `keyword`
strategy gets a perfect MRR (1.000) on `keyword`-type questions - the expected signal that
validates the harness logic before real credentials exist (see `docs/architecture.md`). Mock-mode
quality scores run low because `MockChatModel` quotes retrieved text verbatim rather than
paraphrasing it, so it won't lexically resemble the human-written `expected_answer_summary`
fields; a live-Azure smoke test (`--limit 4`) already shows meaningfully higher scores (~0.16-0.19
vs. ~0.06-0.09 in mock mode) now that generation actually paraphrases.

Service names in document frontmatter are normalised at ingest against the curated concept layer in
`okf/services/*.md` (21 files, one per service, each with its aliases). The corpus was written by
several people, so `lambda`/`Lambda`, `ec2`/`EC2`, `api-gateway`/`API Gateway` and `ELB`/`ALB`/`alb`
all appeared as distinct values and any metadata filter on `services` matched roughly half of what
it should. An unrecognised service name logs a warning naming the `okf/` file that would fix it and
is passed through unchanged - the curated layer is expected to lag the corpus. The skeletons were
generated from the corpus inventory and still need their owning SRE to correct `owned_by`,
`depends_on` and the failure-mode lists in review.

**Known limitations (each fixed once, worth knowing)**:
- `BM25Retriever`'s default tokenizer is a bare `str.split()` with no lowercasing or punctuation
  stripping, so an incident ID like `INC-2025-0101?` (from a question) would never exact-match
  `INC-2025-0101;` (as it appears in a doc). `rag/retrieval/keyword.py` supplies a normalizing
  tokenizer to fix this - worth keeping in mind if keyword-strategy results ever look implausibly
  bad after a dependency upgrade changes `BM25Retriever`'s defaults.
- The citation instruction in `rag/chain/prompt.py` originally read "...copied verbatim from that
  chunk's `[SOURCE: incident_id · section]` header", which `MockChatModel` never had to parse
  correctly (it doesn't read the system prompt at all) but which a real model - the first time
  Azure generation was tested live - took literally, emitting the placeholder text
  `[incident_id · section]` instead of the chunk's real values. Fixed by rephrasing with an
  explicit example and an instruction to never emit the literal words `incident_id`/`section`.
  A reminder that mock-mode passing tests don't exercise prompt wording the way a live model does.

**Real RCA docs** (`data/raw_rca_docs/real/`): five real-world postmortems, normalized into
`docs/rca_doc_template.md`'s format -
[INC-2017-0228-S3-USEAST1](data/raw_rca_docs/real/inc-2017-0228-s3-useast1-outage.md) (AWS S3
capacity-removal outage),
[INC-2023-1102-CF-CONTROLPLANE](data/raw_rca_docs/real/inc-2023-1102-cloudflare-controlplane-outage.md)
(Cloudflare data-center power loss),
[INC-2017-0131-GITLAB-DB](data/raw_rca_docs/real/inc-2017-0131-gitlab-db-incident.md) (GitLab
production database data loss),
[INC-2021-1004-META-BGP](data/raw_rca_docs/real/inc-2021-1004-meta-bgp-outage.md) (Meta global
BGP/DNS outage), and
[INC-2026-0142](data/raw_rca_docs/real/inc-2026-0142-azure-terraform-drift.md) (Azure Terraform
drift destroying a subnet's NSGs). The original source files (.docx/.pdf) remain alongside the
normalized markdown for reference; the loader skips non-markdown files and `real/README.md`
automatically. 17 golden questions (including 2 cross-document ones linking a real incident to a
thematically related synthetic one) were added to cover them.

## Going live

`LLM_PROVIDER` in `.env` selects the provider (`azure` | `bedrock`, default `azure`); everything
else is provider-specific credentials, auto-detected the same way regardless of which is active -
see `docs/architecture.md`.

**Azure (default)**: set `AZURE_AI_ENDPOINT` and `AZURE_AI_KEY` in `.env`. Chat generation goes
live automatically once both are set. Embeddings stay on the mock implementation until
`AZURE_AI_EMBED_MODEL` is also set to a real embedding deployment name - see `infra/azure/` for the
Bicep template (and a `what-if`-verified, prod-safe parameter file) that provisions one on the
existing account without touching its live chat deployment. Both are live and verified end-to-end
today (`gpt-4o-mini` chat, `text-embedding-3-small` embeddings). `AZURE_TENANT_ID`/`AZURE_CLIENT_ID`/
`AZURE_CLIENT_SECRET` are accepted but not yet consumed by any code path - reserved for a future
AD-token auth flow if key auth ever needs to be replaced.

**Bedrock**: set `LLM_PROVIDER=bedrock` and supply real `AWS_ACCESS_KEY_ID` /
`AWS_SECRET_ACCESS_KEY` (and `AWS_SESSION_TOKEN` if applicable) to switch the same commands over
to live AWS Bedrock for both the chat model and embeddings. This code path is unchanged and kept
fully working even while Azure is the active default.

## Hosted frontend

**http://rag-sre-poc-frontend.azurewebsites.net** - `streamlit_app.py` deployed to Azure App
Service (F1 free tier), running fully live against the same Azure AI account as above. No
authentication (a deliberate choice, not an oversight) and no "Always On" (not available below
Basic tier - expect a cold-start delay after ~20 minutes idle). See `deploy/README.md` for the
hosting setup, known limitations, and how to redeploy after a change.

## Layout

- `config/` - environment-driven settings (`config/settings.py`)
- `rag/` - ingestion, embeddings, LLM clients, vector store, retrieval strategies, and the
  question-answering chain
- `cli/` - `ingest`, `query`, and `eval` command-line entry points
- `api/` - optional FastAPI surface over the same chain
- `streamlit_app.py` - interactive test console (see `deploy/README.md` for the hosted version)
- `eval/` - golden question set and retrieval-strategy scoring harness
- `data/raw_rca_docs/` - place RCA markdown docs here (see `docs/rca_doc_template.md`)
- `docs/` - architecture notes and open design questions
- `infra/azure/`, `deploy/` - Bicep provisioning and App Service deployment for the Azure pieces
