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
