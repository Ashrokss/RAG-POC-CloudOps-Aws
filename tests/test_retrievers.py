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

from config.settings import get_settings
from rag.retrieval.factory import STRATEGIES, get_retriever
from rag.vectorstore.chroma_store import build_index

_QUERY = "Lambda reserved concurrency throttling during a traffic spike"
_EXPECTED_DOC_ID = "doc-lambda"


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
