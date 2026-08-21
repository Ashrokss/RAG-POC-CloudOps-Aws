"""
Settings is a process-wide lru_cache singleton (config/settings.py), so
these tests mutate the cached instance's fields via monkeypatch instead of
constructing a fresh Settings() - chroma_store and bedrock_embeddings each
call get_settings() themselves and must see the same forced mock_mode and
persist_dir without patching every module's imported name individually.
"""

from __future__ import annotations

import uuid
from pathlib import Path

import pytest
from langchain_core.documents import Document

from config.settings import get_settings
from rag.embeddings.mock_embeddings import MockBedrockEmbeddings
import rag.vectorstore.chroma_store as chroma_store
from rag.vectorstore.chroma_store import (
    EmbeddingMismatchError,
    build_index,
    get_collection_stats,
    get_vectorstore,
)


@pytest.fixture(autouse=True)
def _mock_chroma_settings(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> None:
    settings = get_settings()
    monkeypatch.setattr(settings, "_mock_mode", True)
    monkeypatch.setattr(settings, "chroma_persist_dir", str(tmp_path))
    monkeypatch.setattr(settings, "chroma_collection_name", "test_collection")


def _make_chunks(n: int) -> list[Document]:
    return [
        Document(
            page_content=f"chunk body {i}",
            metadata={
                "chunk_id": str(uuid.uuid4()),
                "doc_id": str(uuid.uuid4()),
                "incident_id": "INC-TEST-0001",
                "section": "Summary",
                "severity": "high",
                "services": "S3,EC2",
                "date": "2025-01-01T00:00:00+00:00",
                "source": "synthetic",
            },
        )
        for i in range(n)
    ]


def test_build_index_then_stats_reflects_chunk_count() -> None:
    chunks = _make_chunks(5)

    vectorstore = build_index(chunks, reset=True)
    stats = get_collection_stats(vectorstore)

    assert stats["count"] == 5
    assert isinstance(vectorstore.embeddings, MockBedrockEmbeddings)


def test_build_index_reset_false_on_same_chunks_does_not_duplicate() -> None:
    chunks = _make_chunks(3)

    build_index(chunks, reset=True)
    vectorstore = build_index(chunks, reset=False)
    stats = get_collection_stats(vectorstore)

    assert stats["count"] == 3


def test_build_index_stamps_the_embedding_model() -> None:
    vectorstore = build_index(_make_chunks(2), reset=True)

    assert vectorstore._collection.metadata["embedding_model"] == "mock:hash-256"


def test_reading_an_index_built_by_another_embedder_fails_loudly(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    # The deployed console hit this as "Collection expecting embedding with
    # dimension of 256, got 1536", once per strategy, from inside Chroma - and
    # would have hit nothing at all had the two models shared a dimension.
    build_index(_make_chunks(2), reset=True)
    monkeypatch.setattr(
        chroma_store, "embedding_model_id", lambda: "azure:text-embedding-3-small"
    )

    with pytest.raises(EmbeddingMismatchError, match="mock:hash-256"):
        get_vectorstore(MockBedrockEmbeddings())


def test_unstamped_legacy_collection_is_still_readable(monkeypatch: pytest.MonkeyPatch) -> None:
    # Indexes built before the stamp existed carry no provenance; refusing them
    # would break every existing deployment for no safety gain.
    vectorstore = build_index(_make_chunks(2), reset=True)
    vectorstore._collection.modify(metadata={"note": "no embedding_model key"})

    assert get_vectorstore(MockBedrockEmbeddings()) is not None
