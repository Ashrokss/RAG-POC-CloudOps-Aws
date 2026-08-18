"""
The oversized-section fixture repeats a short sentence rather than using one
long unbroken token, because RecursiveCharacterTextSplitter splits on
whitespace/paragraph boundaries - a fixture with nowhere to split would
defeat the point of the test.
"""

from __future__ import annotations

from datetime import datetime, timezone
from typing import Any

from rag.ingestion.chunker import chunk_document
from rag.models import RCADocumentMeta

_EXPECTED_METADATA_KEYS = {
    "chunk_id",
    "doc_id",
    "incident_id",
    "section",
    "severity",
    "services",
    "date",
    "source",
}


def _meta(**overrides: Any) -> RCADocumentMeta:
    fields: dict[str, Any] = dict(
        incident_id="INC-TEST-0001",
        title="Test Incident",
        date=datetime(2025, 1, 1, tzinfo=timezone.utc),
        severity="high",
        services=["S3", "EC2"],
        region="us-east-1",
        account_id="123456789012",
        status="resolved",
        tags=["test"],
        source="synthetic",
    )
    fields.update(overrides)
    return RCADocumentMeta(**fields)


def test_chunk_document_metadata_keys() -> None:
    meta = _meta()
    body = "## Summary\n\nShort summary text.\n"

    chunks = chunk_document(meta, body, chunk_size=800, chunk_overlap=50)

    assert len(chunks) == 1
    chunk = chunks[0]
    assert set(chunk.metadata.keys()) == _EXPECTED_METADATA_KEYS
    assert chunk.metadata["doc_id"] == meta.doc_id
    assert chunk.metadata["incident_id"] == "INC-TEST-0001"
    assert chunk.metadata["section"] == "Summary"
    assert chunk.metadata["severity"] == "high"
    assert chunk.metadata["services"] == "S3,EC2"
    assert chunk.metadata["date"] == meta.date.isoformat()
    assert chunk.metadata["source"] == "synthetic"


def test_chunk_document_splits_on_section_headers() -> None:
    meta = _meta()
    body = "## Summary\n\nShort summary text.\n\n## Root Cause\n\nShort root cause text.\n"

    chunks = chunk_document(meta, body, chunk_size=800, chunk_overlap=50)

    assert len(chunks) == 2
    assert [chunk.metadata["section"] for chunk in chunks] == ["Summary", "Root Cause"]
    assert "summary" in chunks[0].page_content.lower()
    assert "root cause" in chunks[1].page_content.lower()


def test_chunk_document_splits_oversized_section_further() -> None:
    meta = _meta()
    chunk_size = 200
    sentence = "Event happened at some point in time. "
    body = "## Timeline\n\n" + sentence * 60

    chunks = chunk_document(meta, body, chunk_size=chunk_size, chunk_overlap=20)

    assert len(chunks) > 1
    assert all(chunk.metadata["section"] == "Timeline" for chunk in chunks)
    assert all(len(chunk.page_content) <= chunk_size for chunk in chunks)
    assert len({chunk.metadata["chunk_id"] for chunk in chunks}) == len(chunks)


def test_chunk_document_chunk_ids_are_deterministic() -> None:
    # Same document chunked twice must produce the same ids, or the Chroma
    # upsert path degrades into "insert everything again under new ids" and a
    # second ingest silently duplicates the corpus.
    meta = _meta()
    body = "## Summary\n\nShort summary text.\n\n## Root Cause\n\nShort root cause text.\n"

    first = chunk_document(meta, body, chunk_size=800, chunk_overlap=50)
    second = chunk_document(meta, body, chunk_size=800, chunk_overlap=50)

    assert [c.metadata["chunk_id"] for c in first] == [c.metadata["chunk_id"] for c in second]


def test_chunk_document_chunk_ids_differ_across_documents() -> None:
    body = "## Summary\n\nShort summary text.\n"

    first = chunk_document(_meta(), body, chunk_size=800, chunk_overlap=50)
    second = chunk_document(_meta(), body, chunk_size=800, chunk_overlap=50)

    # Two RCADocumentMeta instances get distinct doc_ids, so their chunks must
    # not collide even though section, ordinal and text are identical.
    assert first[0].metadata["chunk_id"] != second[0].metadata["chunk_id"]
