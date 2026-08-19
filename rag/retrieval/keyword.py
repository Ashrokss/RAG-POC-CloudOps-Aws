"""
BM25Retriever.from_documents builds its index in-process from whatever chunk
list it's handed - there's no separate persisted BM25 store to keep in sync
with Chroma, so the retriever is rebuilt from the same chunks on every call
rather than cached. For a corpus this small that's cheaper than the
bookkeeping a persisted index would need.
"""

from __future__ import annotations

import re

from langchain_community.retrievers import BM25Retriever
from langchain_core.documents import Document

_TOKEN_RE = re.compile(r"[a-z0-9]+(?:-[a-z0-9]+)*")


def _tokenize(text: str) -> list[str]:
    """BM25Retriever's default preprocessing is a bare str.split() - no
    lowercasing, no punctuation stripping - so an incident ID like
    "INC-2025-0101" only exact-matches across query and chunk when both
    happen to have identical trailing punctuation (or none). Hyphens are
    kept inside a token so IDs like "INC-2025-0101" and "checkout-order-processor"
    stay single, matchable units instead of splintering into "2025"/"0101"."""
    return _TOKEN_RE.findall(text.lower())


def get_keyword_retriever(chunks: list[Document], k: int) -> BM25Retriever:
    retriever = BM25Retriever.from_documents(chunks, preprocess_func=_tokenize)
    retriever.k = k
    return retriever
