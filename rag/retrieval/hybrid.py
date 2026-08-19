"""
EnsembleRetriever fuses results by reciprocal rank rather than by combining
raw similarity/BM25 scores, which is why weighting semantic against keyword
is meaningful even though the two retrievers' underlying scores live on
incomparable scales.
"""

from __future__ import annotations

from langchain_classic.retrievers import EnsembleRetriever
from langchain_core.retrievers import BaseRetriever


def get_hybrid_retriever(
    semantic_retriever: BaseRetriever,
    keyword_retriever: BaseRetriever,
    weights: tuple[float, float] = (0.5, 0.5),
) -> EnsembleRetriever:
    return EnsembleRetriever(retrievers=[semantic_retriever, keyword_retriever], weights=list(weights))
