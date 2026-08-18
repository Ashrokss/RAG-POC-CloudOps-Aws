"""
Fixtures live in tmp_path rather than pointing at data/raw_rca_docs/ because
the behaviors under test - a bad-frontmatter doc, a README.md sitting next to
real docs - are cases the checked-in corpus deliberately never contains.
"""

from __future__ import annotations

import logging
import uuid
from datetime import datetime, timezone
from pathlib import Path

import pytest

from rag.ingestion.loader import canonical_service, load_rca_documents, parse_frontmatter
from rag.models import RCADocumentMeta

_VALID_FRONTMATTER = """---
incident_id: "INC-TEST-0001"
title: "Test Incident"
date: "2025-01-01T00:00:00Z"
severity: high
services: ["S3", "EC2"]
region: "us-east-1"
account_id: "123456789012"
status: "resolved"
tags: ["test"]
source: synthetic
---

## Summary

Something happened.
"""


def test_parse_frontmatter_splits_metadata_and_body() -> None:
    metadata, body = parse_frontmatter(_VALID_FRONTMATTER)

    assert metadata["incident_id"] == "INC-TEST-0001"
    assert metadata["severity"] == "high"
    assert metadata["services"] == ["S3", "EC2"]
    assert body.strip().startswith("## Summary")


def test_load_rca_documents_happy_path(tmp_path: Path) -> None:
    (tmp_path / "inc-0001.md").write_text(_VALID_FRONTMATTER, encoding="utf-8")

    docs = load_rca_documents([tmp_path])

    assert len(docs) == 1
    meta, body = docs[0]
    assert isinstance(meta, RCADocumentMeta)
    assert meta.incident_id == "INC-TEST-0001"
    assert meta.severity == "high"
    # Normalised against okf/services/ - the frontmatter says ["S3", "EC2"].
    assert meta.services == ["s3", "ec2"]
    assert meta.date == datetime(2025, 1, 1, tzinfo=timezone.utc)
    assert "## Summary" in body


def test_load_rca_documents_missing_required_field_raises(tmp_path: Path) -> None:
    broken = _VALID_FRONTMATTER.replace("severity: high\n", "")
    (tmp_path / "inc-broken.md").write_text(broken, encoding="utf-8")

    with pytest.raises(ValueError, match="Invalid RCA frontmatter"):
        load_rca_documents([tmp_path])


def test_load_rca_documents_skips_readme(tmp_path: Path) -> None:
    (tmp_path / "README.md").write_text("# not an RCA doc\nno frontmatter here.\n", encoding="utf-8")
    (tmp_path / "inc-0001.md").write_text(_VALID_FRONTMATTER, encoding="utf-8")

    docs = load_rca_documents([tmp_path])

    assert len(docs) == 1
    assert docs[0][0].incident_id == "INC-TEST-0001"


def test_load_rca_documents_blank_doc_id_generates_uuid(tmp_path: Path) -> None:
    text = _VALID_FRONTMATTER.replace("---\n", '---\ndoc_id: ""\n', 1)
    (tmp_path / "inc-0001.md").write_text(text, encoding="utf-8")

    docs = load_rca_documents([tmp_path])

    assert uuid.UUID(docs[0][0].doc_id).version == 4


def test_load_rca_documents_normalises_service_aliases(tmp_path: Path) -> None:
    text = _VALID_FRONTMATTER.replace(
        'services: ["S3", "EC2"]', 'services: ["Lambda", "API Gateway"]'
    )
    (tmp_path / "inc-0001.md").write_text(text, encoding="utf-8")

    docs = load_rca_documents([tmp_path])

    assert docs[0][0].services == ["lambda", "api-gateway"]


def test_unknown_service_warns_and_passes_through(
    tmp_path: Path, caplog: pytest.LogCaptureFixture
) -> None:
    # The curated okf/ layer is expected to lag the corpus; an ingest that
    # raises on the first unclaimed service name is an ingest nobody can run.
    text = _VALID_FRONTMATTER.replace('services: ["S3", "EC2"]', 'services: ["kafka"]')
    (tmp_path / "inc-0001.md").write_text(text, encoding="utf-8")

    with caplog.at_level(logging.WARNING, logger="rag.ingestion.loader"):
        docs = load_rca_documents([tmp_path])

    assert docs[0][0].services == ["kafka"]
    assert any("okf/services/kafka.md" in record.getMessage() for record in caplog.records)


def test_canonical_service_is_case_and_spelling_insensitive() -> None:
    assert canonical_service("ELB") == "alb"
    assert canonical_service("alb") == "alb"
    assert canonical_service("ElastiCache for Redis") == "elasticache"
