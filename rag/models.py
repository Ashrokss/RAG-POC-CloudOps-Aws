"""
These models are the shared contract at every boundary the RAG pipeline
crosses - ingestion writes RCADocumentMeta into Chroma metadata, retrieval
builds Citations from what it reads back out, the chain assembles a
RAGAnswer, and eval scores answers against GoldenQuestion. Defining them once
here means a field rename is caught by type-checking every consumer instead
of surfacing as a silent KeyError three modules downstream.
"""

from __future__ import annotations

import uuid
from datetime import datetime, timezone
from typing import Literal

from pydantic import BaseModel, Field, field_validator

RetrievalStrategy = Literal["semantic", "keyword", "hybrid", "hybrid_rerank"]


def _utc_now() -> datetime:
    return datetime.now(timezone.utc)


def _new_uuid4() -> str:
    return str(uuid.uuid4())


def _as_utc(value: datetime) -> datetime:
    # Frontmatter authors and golden-set fixtures routinely hand-write naive
    # datetimes; treat those as already-UTC rather than rejecting them.
    if value.tzinfo is None:
        return value.replace(tzinfo=timezone.utc)
    return value.astimezone(timezone.utc)


class RCADocumentMeta(BaseModel):
    doc_id: str = Field(default_factory=_new_uuid4)
    incident_id: str
    title: str
    date: datetime
    severity: Literal["critical", "high", "medium", "low"]
    services: list[str]
    region: str
    account_id: str
    status: str
    tags: list[str]
    source: Literal["real", "synthetic"]

    @field_validator("date", mode="after")
    @classmethod
    def _normalize_date(cls, value: datetime) -> datetime:
        return _as_utc(value)


class Citation(BaseModel):
    doc_id: str
    incident_id: str
    section: str
    snippet: str


class RAGAnswer(BaseModel):
    question: str
    strategy: RetrievalStrategy
    answer: str
    citations: list[Citation]
    retrieved_doc_ids: list[str]
    latency_ms: float
    model_id: str
    mode: Literal["mock", "live"]
    run_id: str = Field(default_factory=_new_uuid4)
    generated_at: datetime = Field(default_factory=_utc_now)

    @field_validator("generated_at", mode="after")
    @classmethod
    def _normalize_generated_at(cls, value: datetime) -> datetime:
        return _as_utc(value)


class GoldenQuestion(BaseModel):
    qid: str = Field(default_factory=_new_uuid4)
    question: str
    question_type: Literal["factual", "keyword", "semantic", "cross_document"]
    relevant_doc_ids: list[str]
    expected_answer_summary: str
    notes: str = ""
