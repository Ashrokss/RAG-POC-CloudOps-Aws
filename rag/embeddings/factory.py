"""
Every caller (chroma_store, rag_chain, cli.ingest, api.main) imports
get_embeddings from here rather than from a specific provider module, so
flipping LLM_PROVIDER is a config change in .env, not a code change in every
one of those callers.
"""

from __future__ import annotations

from langchain_core.embeddings import Embeddings

from config.settings import get_settings


def embedding_model_id() -> str:
    """Identifies which embedder built (or is querying) an index. Vectors from
    two different models are not comparable - and usually not even the same
    length - so this is what rag/vectorstore/chroma_store.py stamps into the
    collection and checks on the way back in."""
    settings = get_settings()
    if settings.llm_provider == "bedrock":
        if settings.mock_mode:
            return "mock:hash-256"
        return f"bedrock:{settings.bedrock_embed_model_id}"

    if settings.mock_mode or not settings.azure_ai_embed_model:
        return "mock:hash-256"
    return f"azure:{settings.azure_ai_embed_model}"


def get_embeddings() -> Embeddings:
    settings = get_settings()
    if settings.llm_provider == "bedrock":
        from rag.embeddings.bedrock_embeddings import get_embeddings as _get_embeddings
    else:
        from rag.embeddings.azure_embeddings import get_embeddings as _get_embeddings
    return _get_embeddings()
