"""
Every record that crosses a boundary in this system, typed once.

The three planes from the design are a field, not three schemas: a row in
`docs` is evidence, concept, or candidate, and the plane decides whether
retrieval may see it. One table means promotion is an UPDATE and an audit
row, not a copy between stores that can half-fail.

Ids are content-derived wherever a thing can be re-ingested. The predecessor
system minted chunk ids from uuid4() on every call, so the same chunk carried
one id in the vector store and a different one in memory - re-ingest silently
duplicated the corpus and nothing could be cached or diffed. Deterministic
ids make ingest idempotent by construction.
"""

from __future__ import annotations

import hashlib
from datetime import datetime, timezone
from typing import Literal, Optional

from pydantic import BaseModel, Field

Plane = Literal["evidence", "concept", "candidate"]
SourceTier = Literal["internal", "reference", "web"]
GapStatus = Literal["open", "researching", "candidate", "resolved", "abandoned"]
CandidateStatus = Literal["draft", "ai_verified", "ai_rejected", "approved", "rejected", "promoted"]
Route = Literal["retrieval", "aggregate", "gap"]


def utc_now() -> datetime:
    return datetime.now(timezone.utc)


def stable_id(*parts: object) -> str:
    return hashlib.sha1("|".join(str(p) for p in parts).encode("utf-8")).hexdigest()[:16]


class SourceDoc(BaseModel):
    """One ingested document, whatever adapter produced it."""

    doc_id: str
    source_uri: str
    plane: Plane = "evidence"
    source_tier: SourceTier = "internal"
    title: str
    body: str

    # Incident fields. Optional because a vendor doc or a promoted knowledge
    # card is a document too, and has no incident id or severity.
    incident_id: Optional[str] = None
    date: Optional[datetime] = None
    severity: Optional[str] = None
    services: list[str] = Field(default_factory=list)
    region: Optional[str] = None
    status: Optional[str] = None
    tags: list[str] = Field(default_factory=list)
    detection_gap_minutes: Optional[int] = None
    duration_minutes: Optional[int] = None
    cost_usd: Optional[float] = None

    retrieved_at: datetime = Field(default_factory=utc_now)
    review_ttl_days: Optional[int] = None

    @property
    def content_hash(self) -> str:
        return stable_id(self.body)


class Chunk(BaseModel):
    chunk_id: str
    doc_id: str
    section: str
    ordinal: int
    text: str

    # Denormalised onto the chunk so retrieval can filter without a join, and
    # so a returned chunk is self-describing when it lands in a prompt.
    incident_id: Optional[str] = None
    # What a citation shows. An incident cites as INC-2025-0101; a promoted
    # vendor-doc card cited as its doc_id hash, which tells a reader nothing
    # about where the claim came from.
    label: str = ""
    plane: Plane = "evidence"
    source_tier: SourceTier = "internal"
    services: list[str] = Field(default_factory=list)

    @property
    def cite_key(self) -> str:
        return self.incident_id or self.label or self.doc_id

    @property
    def search_text(self) -> str:
        """What retrieval indexes, as opposed to what a prompt displays.

        A chunk usually does not repeat its own incident id - only 2 of 11
        chunks of INC-2025-0101 mention it - so a question naming an id could
        not find the document it names, by either BM25 or embedding. Retrieval
        answered a question about INC-2025-0101 with INC-2025-1002's root
        cause, confidently and with a citation, because nothing in the index
        connected the id to the text. Prefixing the identity fixes both
        retrievers at once.
        """
        return f"[{self.cite_key} · {self.section}]\n{self.text}"


class Retrieved(BaseModel):
    chunk: Chunk
    score: float


class KnowledgeGap(BaseModel):
    """A question the corpus could not answer. The trigger for everything in
    rca/research.py - and the reason refusal has to be a first-class outcome
    rather than a failure: a system that always answers never learns what it
    does not know."""

    gap_id: str
    question: str
    reason: Literal["low_coverage", "refused", "unknown_entity"]
    best_score: float = 0.0
    hit_count: int = 1
    status: GapStatus = "open"
    first_seen: datetime = Field(default_factory=utc_now)
    last_seen: datetime = Field(default_factory=utc_now)


class Evidence(BaseModel):
    """One external source backing a claim. `quote` must appear verbatim in
    the fetched text - rca/verify.py checks exactly that."""

    url: str
    title: str = ""
    quote: str
    authority: Literal["vendor_doc", "official_postmortem", "community", "unknown"] = "unknown"


class CandidateCard(BaseModel):
    """Knowledge learned from outside, quarantined until a human promotes it."""

    candidate_id: str
    gap_id: str
    claim: str
    applies_to: list[str] = Field(default_factory=list)
    failure_mode: Optional[str] = None
    evidence: list[Evidence] = Field(default_factory=list)
    confidence: float = 0.0
    status: CandidateStatus = "draft"
    verdict: Optional["Verdict"] = None
    created_at: datetime = Field(default_factory=utc_now)
    reviewed_by: Optional[str] = None
    review_reason: Optional[str] = None


class Verdict(BaseModel):
    """Output of the adversarial verifier. `approved` here means "fit for a
    human to look at", never "fit to publish"."""

    approved: bool
    quotes_verified: int = 0
    quotes_total: int = 0
    authority_score: float = 0.0
    conflicts: list[str] = Field(default_factory=list)
    votes_for: int = 0
    votes_total: int = 0
    notes: list[str] = Field(default_factory=list)


class Answer(BaseModel):
    question: str
    route: Route
    answer: str
    citations: list[str] = Field(default_factory=list)
    retrieved_chunk_ids: list[str] = Field(default_factory=list)
    coverage: float = 0.0
    gap_id: Optional[str] = None
    latency_ms: float = 0.0
    model_id: str = ""


class FiveWhy(BaseModel):
    why: str
    because: str
    citations: list[str] = Field(default_factory=list)


class RCAReport(BaseModel):
    """Typed, not prose. Every field carries its own citations, so coverage is
    measurable per field instead of per answer, and the model's gaps show up in
    unsupported_fields rather than being smoothed into fluent paragraphs.

    A generated report re-enters the pipeline as a candidate - the system does
    not trust its own output because it produced it.
    """

    incident_id: str
    summary: str = ""
    timeline: list[str] = Field(default_factory=list)
    impact: str = ""
    root_cause: str = ""
    five_whys: list[FiveWhy] = Field(default_factory=list)
    contributing_factors: list[str] = Field(default_factory=list)
    detection: str = ""
    mitigation: list[str] = Field(default_factory=list)
    action_items: list[str] = Field(default_factory=list)
    similar_incidents: list[str] = Field(default_factory=list)
    evidence_map: dict[str, list[str]] = Field(default_factory=dict)
    unsupported_fields: list[str] = Field(default_factory=list)
    generated_at: datetime = Field(default_factory=utc_now)


CandidateCard.model_rebuild()
