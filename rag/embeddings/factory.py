"""
Every caller (chroma_store, rag_chain, cli.ingest, api.main) imports
get_embeddings from here rather than from a specific provider module, so
flipping LLM_PROVIDER is a config change in .env, not a code change in every
one of those callers.
"""

from __future__ import annotations

from langchain_core.embeddings import Embeddings

from config.settings import get_settings


def get_embeddings() -> Embeddings:
    settings = get_settings()
    if settings.llm_provider == "bedrock":
        from rag.embeddings.bedrock_embeddings import get_embeddings as _get_embeddings
    else:
        from rag.embeddings.azure_embeddings import get_embeddings as _get_embeddings
    return _get_embeddings()
