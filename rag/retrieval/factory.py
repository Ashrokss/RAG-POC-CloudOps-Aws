"""
hybrid_rerank builds its underlying hybrid retriever at k*2 rather than k:
reranking only has something to do if it's handed more candidates than it's
asked to return, and EnsembleRetriever's rank fusion already discards the
tail of each individual ranking, so requesting the final k up front would
leave the reranker nothing to actually reorder.
"""

from __future__ import annotations

from langchain_core.documents import Document
from langchain_core.retrievers import BaseRetriever
from langchain_core.vectorstores import VectorStore

from config.settings import get_settings
from rag.retrieval.hybrid import get_hybrid_retriever
from rag.retrieval.keyword import get_keyword_retriever
from rag.retrieval.rerank import get_reranked_retriever
from rag.retrieval.semantic import get_semantic_retriever

STRATEGIES = ("semantic", "keyword", "hybrid", "hybrid_rerank")


def get_retriever(
    name: str, vectorstore: VectorStore | None, chunks: list[Document], k: int
) -> BaseRetriever:
    """vectorstore may be None for the keyword strategy, which is BM25 over the
    chunk list and never reads the vector store."""
    if name == "semantic":
        return get_semantic_retriever(vectorstore, k)
    if name == "keyword":
        return get_keyword_retriever(chunks, k)
    if name == "hybrid":
        return get_hybrid_retriever(get_semantic_retriever(vectorstore, k), get_keyword_retriever(chunks, k))
    if name == "hybrid_rerank":
        wide_k = k * 2
        wide_hybrid = get_hybrid_retriever(get_semantic_retriever(vectorstore, wide_k), get_keyword_retriever(chunks, wide_k))
        return get_reranked_retriever(wide_hybrid, get_settings().rerank_provider, top_n=k)

    raise ValueError(f"Unknown retrieval strategy: {name!r}. Valid strategies: {STRATEGIES}")
