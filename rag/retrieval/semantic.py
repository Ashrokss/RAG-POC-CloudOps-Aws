"""
Thin wrapper around VectorStore.as_retriever so every strategy in this
package is reached through get_retriever(name, ...) with the same shape,
instead of callers reaching into vectorstore.as_retriever(...) directly for
this one case and through a factory for the other three.
"""

from __future__ import annotations

from langchain_core.retrievers import BaseRetriever
from langchain_core.vectorstores import VectorStore


def get_semantic_retriever(vectorstore: VectorStore, k: int) -> BaseRetriever:
    return vectorstore.as_retriever(search_type="similarity", search_kwargs={"k": k})
