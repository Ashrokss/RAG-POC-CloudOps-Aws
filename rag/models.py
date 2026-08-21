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
from typing import Literal, Optional

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

    # Aggregate-question fields. Optional because they are extracted by a human
    # from the doc's own Impact/Detection sections at authoring time, and older
    # docs (plus the RCA template) predate them. They exist as frontmatter, not
    # as something parsed out of prose at query time, because "which incident
    # had the longest detection gap" has to be answerable by sorting a column -
    # a top-k retriever only ever sees k documents and structurally cannot
    # answer it. cost_usd is the impact recorded for this organisation: a
    # third-party estimate of industry-wide loss (INC-2017-0228) is left null
    # here and stays in the prose, or it would dominate every cost total.
    detection_gap_minutes: Optional[int] = None
    duration_minutes: Optional[int] = None
    cost_usd: Optional[float] = None

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
    # Which path produced this answer. Surfaced (not internal) because a
    # reviewer reading an enumeration or a total has to be able to see whether
    # it came from the complete incident index, the okf/ dependency graph, or
    # k retrieved chunks.
    route: Literal["retrieval", "aggregate", "blast_radius"] = "retrieval"
    # True when the answer carries a general-knowledge section. Surfaced for
    # the same reason as route: a reader deciding whether to act on an answer
    # needs to know part of it rests on nothing in this corpus.
    used_outside_knowledge: bool = False
    run_id: str = Field(default_factory=_new_uuid4)
    generated_at: datetime = Field(default_factory=_utc_now)

    @field_validator("generated_at", mode="after")
    @classmethod
    def _normalize_generated_at(cls, value: datetime) -> datetime:
        return _as_utc(value)


class GoldenQuestion(BaseModel):
    qid: str = Field(default_factory=_new_uuid4)
    question: str
    question_type: Literal[
        "factual", "keyword", "semantic", "cross_document", "aggregate", "unanswerable", "blast_radius"
    ]
    # Optional so an adversarial entry can be authored without hand-copying
    # doc-id UUIDs: must_mention_ids carries incident ids, which the eval
    # runner resolves to doc ids against the incident table. A refusal question
    # has no relevant document by construction.
    relevant_doc_ids: list[str] = Field(default_factory=list)
    expected_answer_summary: str = ""
    notes: str = ""

    # Adversarial scoring fields. All three default to the inert value, so the
    # existing 88-question golden file loads unchanged and is still scored by
    # the Jaccard judge; a question that sets any of them is scored on these
    # instead. Ids here are incident ids (INC-YYYY-NNNN), not doc ids - that is
    # what a human writing a trap question actually knows.
    expects_refusal: bool = False
    must_mention_ids: list[str] = Field(default_factory=list)
    forbidden_ids: list[str] = Field(default_factory=list)

    @property
    def is_adversarial(self) -> bool:
        return bool(self.expects_refusal or self.must_mention_ids or self.forbidden_ids)
