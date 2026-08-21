"""
Every strategy is driven through get_retriever(...) rather than by
instantiating rag/retrieval/semantic.py, keyword.py, hybrid.py, and rerank.py
directly, so this test exercises the same factory surface every real caller
(rag_chain.retrieve_only, cli/query.py) goes through instead of the four
modules it dispatches to.
"""

from __future__ import annotations

from pathlib import Path

import pytest
from langchain_chroma import Chroma
from langchain_core.documents import Document

import rag.chain.rag_chain as rag_chain_module
from config.settings import get_settings
from rag.retrieval.factory import STRATEGIES, get_retriever
from rag.vectorstore.chroma_store import build_index

_QUERY = "Lambda reserved concurrency throttling during a traffic spike"
_EXPECTED_DOC_ID = "doc-lambda"


def _wide_corpus() -> list[Document]:
    """More chunks than the largest k under test, so a strategy that fails to
    truncate has something to over-return - sample_chunks' four documents would
    make len(docs) <= 10 pass for free."""
    return [
        Document(
            page_content=f"Incident {i}: reserved concurrency throttling during a traffic spike on service {i}.",
            metadata={
                "chunk_id": f"chunk-{i}",
                "doc_id": f"doc-{i}",
                "incident_id": f"INC-WIDE-{i:04d}",
                "section": "Root Cause",
                "severity": "high",
                "services": "lambda",
                "date": "2025-01-01T00:00:00+00:00",
                "source": "synthetic",
            },
        )
        for i in range(24)
    ]


@pytest.fixture
def vectorstore(tmp_path: Path, monkeypatch: pytest.MonkeyPatch, sample_chunks: list[Document]) -> Chroma:
    monkeypatch.setenv("CHROMA_PERSIST_DIR", str(tmp_path / "chroma"))
    monkeypatch.setenv("CHROMA_COLLECTION_NAME", "retriever_test")
    get_settings.cache_clear()
    return build_index(sample_chunks, reset=True)


@pytest.mark.parametrize("strategy", STRATEGIES)
def test_strategy_returns_matching_document(vectorstore: Chroma, sample_chunks: list[Document], strategy: str) -> None:
    retriever = get_retriever(strategy, vectorstore, sample_chunks, k=2)

    results = retriever.invoke(_QUERY)

    assert isinstance(results, list)
    assert len(results) > 0
    assert all(isinstance(doc, Document) for doc in results)
    assert any(doc.metadata["doc_id"] == _EXPECTED_DOC_ID for doc in results)


# retrieve_only (not get_retriever) is what every caller and the eval harness
# actually goes through, and it is where the k cap lives - the retrievers
# themselves still disagree about how many documents they hand back, which is
# exactly the bug this guards.
@pytest.mark.parametrize("strategy", STRATEGIES)
@pytest.mark.parametrize("k", [1, 3, 5, 10])
def test_retrieve_only_never_returns_more_than_k(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch, strategy: str, k: int
) -> None:
    chunks = _wide_corpus()
    monkeypatch.setenv("CHROMA_PERSIST_DIR", str(tmp_path / "chroma"))
    monkeypatch.setenv("CHROMA_COLLECTION_NAME", f"k_cap_test_{strategy}_{k}")
    get_settings.cache_clear()
    monkeypatch.setattr(rag_chain_module, "_corpus_chunks", lambda: chunks)
    build_index(chunks, reset=True)

    docs = rag_chain_module.retrieve_only(_QUERY, strategy, k)

    assert len(docs) <= k
    assert len({doc.metadata["chunk_id"] for doc in docs}) == len(docs)


def test_keyword_strategy_needs_no_vector_store() -> None:
    # It is BM25 over the chunk list. Requiring a Chroma handle made an
    # embedding-model mismatch break the one strategy with no embeddings.
    retriever = get_retriever("keyword", None, _wide_corpus(), k=3)

    results = retriever.invoke(_QUERY)

    assert 0 < len(results) <= 3
