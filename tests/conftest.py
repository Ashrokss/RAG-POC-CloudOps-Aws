"""
Both BEDROCK_MOCK_MODE and AZURE_MOCK_MODE are forced true (rather than
relying on Settings' own credential autodetection for whichever provider is
active) so this suite stays offline and deterministic regardless of
LLM_PROVIDER and even on a machine whose .env has real AWS or Azure
credentials configured. The Settings cache is cleared before and after every
test so a CHROMA_PERSIST_DIR override in one test can't leak a stale Settings
instance into the next.
"""

from __future__ import annotations

from collections.abc import Iterator

import pytest
from langchain_core.documents import Document

from config.settings import get_settings


@pytest.fixture(autouse=True)
def _mock_mode(monkeypatch: pytest.MonkeyPatch) -> Iterator[None]:
    monkeypatch.setenv("BEDROCK_MOCK_MODE", "true")
    monkeypatch.setenv("AZURE_MOCK_MODE", "true")
    get_settings.cache_clear()
    yield
    get_settings.cache_clear()


@pytest.fixture
def sample_chunks() -> list[Document]:
    return [
        Document(
            page_content=(
                "Lambda functions started throttling once reserved concurrency "
                "was exhausted during the traffic spike."
            ),
            metadata={
                "chunk_id": "chunk-lambda",
                "doc_id": "doc-lambda",
                "incident_id": "INC-LAMBDA",
                "section": "Root Cause",
                "severity": "high",
                "services": "lambda",
                "date": "2025-02-01T00:00:00+00:00",
                "source": "synthetic",
            },
        ),
        Document(
            page_content=(
                "The RDS connection pool was exhausted after a deploy left idle "
                "connections open past their timeout."
            ),
            metadata={
                "chunk_id": "chunk-rds",
                "doc_id": "doc-rds",
                "incident_id": "INC-RDS",
                "section": "Root Cause",
                "severity": "critical",
                "services": "rds",
                "date": "2025-01-01T00:00:00+00:00",
                "source": "synthetic",
            },
        ),
        Document(
            page_content=(
                "A DynamoDB hot partition formed when a single tenant id "
                "absorbed most of the write traffic."
            ),
            metadata={
                "chunk_id": "chunk-ddb",
                "doc_id": "doc-ddb",
                "incident_id": "INC-DDB",
                "section": "Root Cause",
                "severity": "medium",
                "services": "dynamodb",
                "date": "2025-07-01T00:00:00+00:00",
                "source": "synthetic",
            },
        ),
        Document(
            page_content=(
                "An S3 bucket policy change accidentally blocked cross-account "
                "replication writes."
            ),
            metadata={
                "chunk_id": "chunk-s3",
                "doc_id": "doc-s3",
                "incident_id": "INC-S3",
                "section": "Root Cause",
                "severity": "low",
                "services": "s3",
                "date": "2025-03-01T00:00:00+00:00",
                "source": "synthetic",
            },
        ),
    ]
