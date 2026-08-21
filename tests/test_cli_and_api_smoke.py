"""
Both endpoints are exercised against the same small monkeypatched corpus
test_rag_chain.py uses, rather than the real data/raw_rca_docs tree, so this
smoke test can't fail (or silently pass) depending on what's currently
ingested into ./data/chroma_db on the machine running it.
"""

from __future__ import annotations

from pathlib import Path

import pytest
from fastapi.testclient import TestClient
from langchain_core.documents import Document

import rag.chain.rag_chain as rag_chain_module
from api.main import app
from config.settings import get_settings
from rag.vectorstore.chroma_store import build_index


def _index_small_corpus(tmp_path: Path, monkeypatch: pytest.MonkeyPatch, sample_chunks: list[Document]) -> None:
    monkeypatch.setenv("CHROMA_PERSIST_DIR", str(tmp_path / "chroma"))
    monkeypatch.setenv("CHROMA_COLLECTION_NAME", "api_smoke_test")
    get_settings.cache_clear()
    monkeypatch.setattr(rag_chain_module, "_corpus_chunks", lambda: sample_chunks)
    build_index(sample_chunks, reset=True)


def test_health_reports_mock_mode(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch, sample_chunks: list[Document]
) -> None:
    _index_small_corpus(tmp_path, monkeypatch, sample_chunks)
    client = TestClient(app)

    response = client.get("/health")

    assert response.status_code == 200
    body = response.json()
    assert body["status"] == "ok"
    assert body["mode"] == "mock"


def test_query_returns_well_formed_answer(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch, sample_chunks: list[Document]
) -> None:
    _index_small_corpus(tmp_path, monkeypatch, sample_chunks)
    client = TestClient(app)

    response = client.post("/query", json={"question": "Why did Lambda start throttling?"})

    assert response.status_code == 200
    body = response.json()
    assert isinstance(body["answer"], str)
    assert body["answer"] != ""
    assert len(body["retrieved_doc_ids"]) > 0
