# Architecture

## Two providers, one seam

`LLM_PROVIDER` (`azure` | `bedrock`, default `azure`) selects which pair of provider
modules `rag/llm/factory.py` and `rag/embeddings/factory.py` dispatch to - every other
module (`rag_chain`, `eval/answer_quality`, `retrieval/rerank`, `cli/ingest`, `api/main`)
imports `get_chat_model`/`get_embeddings` from those two factories, never from a specific
provider module, so switching provider is a `.env` change, not a code change.

- **Azure** (`rag/llm/azure_llm.py`, `rag/embeddings/azure_embeddings.py`) - the active
  default. Wraps `azure.ai.inference.ChatCompletionsClient`/`EmbeddingsClient` directly,
  copying the endpoint-shaping logic (append `/openai/deployments/{model}` for a bare
  `cognitiveservices.azure.com` host) from CloudOps-AWS's
  `backend-agent/utils/model_client.py`, since that's the one component already proven
  to work against this exact class of Azure AI Foundry resource. Embeddings stay on the
  mock implementation even when the chat model is live if `AZURE_AI_EMBED_MODEL` isn't
  set - no embedding deployment has been provisioned yet, and a working generation path
  shouldn't be blocked on one.
- **Bedrock** (`rag/llm/bedrock_llm.py`, `rag/embeddings/bedrock_embeddings.py`) - kept
  fully working, not deleted, for when the project moves back to Bedrock. Flip
  `LLM_PROVIDER=bedrock` in `.env` to reactivate it; nothing else needs to change.

## Mock mode: fakes, not stubs

When neither provider's credentials are available, this POC runs against deterministic
fake implementations of LangChain's `Embeddings` and `BaseChatModel` interfaces (see
`rag/embeddings/mock_embeddings.py` and `rag/llm/mock_chat_model.py`) - not
`NotImplementedError` stubs. The fakes produce stable, content-derived output (e.g. a
hash-seeded embedding vector, a templated answer built from the retrieved chunks), so
the same query against the same corpus returns the same answer on every run. Both
providers' mock-mode resolution (`AZURE_MOCK_MODE` / `BEDROCK_MOCK_MODE`, each
auto-detected from that provider's own credentials if unset) share this one pair of
fakes rather than each needing their own.

This is a deliberate departure from the sibling CloudOps-AWS project's fail-fast
`ModelClient` pattern, where missing credentials should abort immediately. Here, the
goal is for the eval harness (`eval/`) and the four retrieval strategies below to
produce comparable, non-trivial signal - which strategy retrieves which chunks, how
citations differ - before real credentials exist. A fail-fast stub would make that
development loop impossible. `tests/conftest.py` forces both providers' mock-mode
env vars to keep the test suite offline regardless of which provider is active or what
real credentials happen to be sitting in `.env`.

## Four retrieval strategies

| Strategy | Expected to win on |
|---|---|
| `semantic` | Paraphrased or conceptual questions with no shared vocabulary with the source doc |
| `keyword` (BM25) | Exact identifiers - incident IDs, service names, error codes, account IDs |
| `hybrid` | Mixed queries where sparse and dense signals surface different but complementary chunks |
| `hybrid_rerank` | Precision at low top-k, by re-scoring hybrid's broader candidate set with a reranker |

`cli/query.py --strategy` and the eval harness both run all four against the same golden
question set so the tradeoffs are visible instead of assumed.

## One seam for the vector store

Every module above `rag/vectorstore/chroma_store.py` talks to LangChain's `VectorStore`
interface, never to `chromadb` directly. See `docs/open-questions.md` for why - it's the
DynamoDB migration path in one paragraph.


## Two routes, one answer path

`rag/routing/router.py` classifies each question before retrieval runs. Questions asking
to count, rank, enumerate or total ("how many", "list every", "longest", "total") take the
**aggregate** route; everything else takes the ordinary **retrieval** route. The split
exists because top-k retrieval is structurally incapable of the first kind: the model only
ever sees k chunks, so "which incident had the longest detection gap" cannot be answered
correctly by a better reranker, only by looking at every incident.

The aggregate route builds the incident index (`rag/routing/incident_table.py`) - one row
per document with date, severity, services, status, and the three hand-extracted fields
`detection_gap_minutes`, `duration_minutes`, `cost_usd` - filters it by any service the
question named, and hands the model those rows *plus* chunk text for each listed incident,
so an enumerated answer can still cite real excerpts rather than assert from metadata.
`RAGAnswer.route` records which path ran; the Streamlit console and the eval records both
surface it.

Classification is a regex, not an LLM call: the trigger vocabulary is small and closed, and
a model round-trip to decide the route would add a second failure mode to a decision that
does not need one. Over-triggering is the cheap direction - the aggregate route still runs
normal retrieval and still cites chunk text, it just also hands over the index.

## The concept layer (`okf/`)

`okf/services/*.md` is a curated, human-reviewed file per service: canonical id, the
aliases actually seen in the corpus, `depends_on`, `owned_by`, and its known failure modes
linked to the incidents that exhibited them. `rag/ingestion/loader.py` normalises every
`services` value in document frontmatter against it at ingest.

Before this, `services` was free text written by several people - `lambda` and `Lambda` (5
docs each), `ec2`/`EC2`, `api-gateway`/`API Gateway`, `ELB`/`ALB`/`alb` - so any metadata
filter matched roughly half the corpus it should have, which is why the aggregate route
above had to wait for it. An unrecognised service name is a warning naming the `okf/` file
that would fix it, never an exception: the curated layer is expected to lag the corpus, and
an ingest that refuses to run until someone writes a concept file is an ingest nobody runs.

The failure-mode files these link to (`okf/failure-modes/*.md`), the playbook layer and the
dependency graph are deliberately not built yet - the service files are the ones the
routing layer actually consumes today.
