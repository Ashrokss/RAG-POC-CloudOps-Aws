# Open Questions

## Storage layer: DynamoDB vs. a vector-capable engine

Production is planned to run on DynamoDB, which has no native vector-similarity search. This POC's
storage layer is deliberately scoped to LangChain's `VectorStore` interface, with exactly one module -
`rag/vectorstore/chroma_store.py` - aware that Chroma is the concrete implementation. Every other
module (ingestion, retrieval, chain, eval) talks to the `VectorStore` interface, not to Chroma
directly.

This is not an accident of convenience: it means pairing DynamoDB with a vector-capable engine later
(OpenSearch Serverless's vector engine, Aurora with pgvector, or Bedrock Knowledge Bases backed by
either) should mean adding one new module that implements the same function signatures as
`chroma_store.py`, not a rewrite of the ingestion or retrieval layers built on top of it.

Decision on which of those three options to use is deferred to the CloudOps-AWS merge, once the
production DynamoDB schema and access patterns are settled.
