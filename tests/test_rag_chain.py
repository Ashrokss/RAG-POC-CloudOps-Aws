"""
_corpus_chunks is monkeypatched to a small fixed corpus rather than letting
retrieve_only read the real data/raw_rca_docs tree, so this test stays
correct regardless of how many incidents get added there later and never
depends on a chroma_db directory a previous ingest run may or may not have
already populated on disk.
"""

from __future__ import annotations

from datetime import datetime, timezone
from pathlib import Path

import pytest
from langchain_core.documents import Document

import rag.chain.rag_chain as rag_chain_module
from config.settings import get_settings
from rag.chain.rag_chain import answer_question
from rag.models import RAGAnswer, RCADocumentMeta
from rag.vectorstore.chroma_store import build_index


def test_answer_question_returns_well_formed_answer(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch, sample_chunks: list[Document]
) -> None:
    monkeypatch.setenv("CHROMA_PERSIST_DIR", str(tmp_path / "chroma"))
    monkeypatch.setenv("CHROMA_COLLECTION_NAME", "rag_chain_test")
    get_settings.cache_clear()
    monkeypatch.setattr(rag_chain_module, "_corpus_chunks", lambda: sample_chunks)
    build_index(sample_chunks, reset=True)

    answer = answer_question("Why did Lambda start throttling?", strategy="hybrid")

    assert isinstance(answer, RAGAnswer)
    assert answer.mode == "mock"
    assert answer.answer != ""
    assert len(answer.retrieved_doc_ids) > 0
    assert answer.latency_ms >= 0


def test_corpus_is_loaded_once_across_repeated_queries(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    # Reading and re-chunking every RCA file per query is the cost this cache
    # exists to remove; an eval run pays it once per (question x strategy)
    # otherwise.
    monkeypatch.setenv("CHROMA_PERSIST_DIR", str(tmp_path / "chroma"))
    monkeypatch.setenv("CHROMA_COLLECTION_NAME", "corpus_cache_test")
    get_settings.cache_clear()

    meta = RCADocumentMeta(
        incident_id="INC-CACHE-0001",
        title="Cached Incident",
        date=datetime(2025, 1, 1, tzinfo=timezone.utc),
        severity="high",
        services=["lambda"],
        region="us-east-1",
        account_id="123456789012",
        status="resolved",
        tags=["cache"],
        source="synthetic",
    )
    body = "## Root Cause\n\nReserved concurrency was exhausted during the spike.\n"

    load_calls: list[object] = []

    def _counting_loader(root_dirs: object) -> list[tuple[RCADocumentMeta, str]]:
        load_calls.append(root_dirs)
        return [(meta, body)]

    monkeypatch.setattr(rag_chain_module, "load_rca_documents", _counting_loader)
    build_index(rag_chain_module._corpus_chunks(), reset=True)

    for _ in range(10):
        rag_chain_module.retrieve_only("Why did Lambda throttle?", "hybrid", k=3)

    assert len(load_calls) == 1
