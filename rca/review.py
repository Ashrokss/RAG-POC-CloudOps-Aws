"""
The human gate, and the only path into the concept plane.

Approval writes a markdown card into knowledge/cards/ and re-ingests it. That
file is the point: the concept layer lives in git, so promotion is reviewable,
diffable, attributable and revertible with tools the team already uses. A
knowledge base you cannot `git blame` is one nobody trusts a year later.

Three properties this enforces:

  - Only a named person approves. `actor` is required, recorded in the audit
    log, and written into the card's frontmatter.
  - Rejection needs a reason, and leaves the gap open. A rejected card that
    silently closed its gap would teach the system to stop asking.
  - Every approved card gets a review TTL. AWS quotas change; stale reference
    data is worse than none, because people stop checking it.
"""

from __future__ import annotations

import re
from pathlib import Path

from rca.ingest import ingest_doc
from rca.models import CandidateCard, SourceDoc, stable_id, utc_now
from rca.providers import Embedder, get_embedder
from rca.retrieve import Retriever
from rca.store import Store

CARDS_DIR = Path(__file__).resolve().parents[1] / "knowledge" / "cards"
DEFAULT_TTL_DAYS = 180


def _slug(text: str) -> str:
    return re.sub(r"[^a-z0-9]+", "-", text.lower()).strip("-")[:60] or "card"


def render_card(card: CandidateCard, actor: str) -> str:
    lines = [
        "---",
        "type: knowledge_card",
        f"id: {card.candidate_id}",
        f"title: {card.claim[:80]}",
        f"applies_to: [{', '.join(repr(s) for s in card.applies_to)}]",
        f"failure_mode: {card.failure_mode or 'null'}",
        f"gap_id: {card.gap_id}",
        f"approved_by: {actor}",
        f"approved_at: {utc_now().isoformat()}",
        f"review_ttl_days: {DEFAULT_TTL_DAYS}",
        f"confidence: {card.confidence}",
        "---",
        "",
        "## Claim",
        "",
        card.claim,
        "",
        "## Evidence",
        "",
    ]
    for item in card.evidence:
        lines += [f"- [{item.title or item.url}]({item.url}) ({item.authority})", f"  > {item.quote}", ""]
    if card.verdict and card.verdict.notes:
        lines += ["## Verifier notes", ""] + [f"- {n}" for n in card.verdict.notes] + [""]
    return "\n".join(lines)


def approve(
    store: Store,
    candidate_id: str,
    actor: str,
    retriever: Retriever | None = None,
    embedder: Embedder | None = None,
    cards_dir: Path | None = None,
) -> Path:
    card = store.get_candidate(candidate_id)
    if card is None:
        raise ValueError(f"no candidate {candidate_id!r}")
    if card.status not in ("ai_verified", "ai_rejected"):
        # ai_rejected is still approvable: a human may overrule the verifier,
        # and that override is exactly what the audit log exists to record.
        raise ValueError(f"candidate {candidate_id!r} is {card.status}, not reviewable")

    cards_dir = cards_dir or CARDS_DIR
    cards_dir.mkdir(parents=True, exist_ok=True)
    path = cards_dir / f"{_slug(card.claim)}-{card.candidate_id[:8]}.md"
    path.write_text(render_card(card, actor), encoding="utf-8")

    doc = SourceDoc(
        doc_id=stable_id(path.as_posix()),
        source_uri=path.as_posix(),
        plane="concept",
        source_tier="reference",
        # Titled by its source, not by the first 120 characters of the claim:
        # the title becomes the citation a reader sees.
        title=(card.evidence[0].title if card.evidence else card.claim)[:80],
        body=render_card(card, actor).split("---", 2)[-1],
        services=card.applies_to,
        review_ttl_days=DEFAULT_TTL_DAYS,
    )
    ingest_doc(store, doc, embedder or get_embedder(), ingest_run=f"promote:{card.candidate_id}")
    if retriever is not None:
        # Otherwise the keyword index keeps answering from the world as it was
        # before this card existed.
        retriever.invalidate()

    card.status = "promoted"
    card.reviewed_by = actor
    store.save_candidate(card)
    store.set_gap_status(card.gap_id, "resolved")
    store.audit(actor, "candidate_promoted", card.candidate_id, path.as_posix())
    return path


def reject(store: Store, candidate_id: str, actor: str, reason: str) -> CandidateCard:
    if not reason.strip():
        raise ValueError("a rejection needs a reason - it is the only record of why")
    card = store.get_candidate(candidate_id)
    if card is None:
        raise ValueError(f"no candidate {candidate_id!r}")

    card.status = "rejected"
    card.reviewed_by = actor
    card.review_reason = reason
    store.save_candidate(card)
    # The gap stays open on purpose: the question is still unanswered, and the
    # next research pass should try again rather than treat it as settled.
    store.set_gap_status(card.gap_id, "open")
    store.audit(actor, "candidate_rejected", card.candidate_id, reason[:200])
    return card


def queue(store: Store) -> list[CandidateCard]:
    """What a reviewer sees: verified first, then the ones the AI rejected -
    which still need a human, because a verifier that silently bins cards is a
    verifier nobody audits."""
    return store.candidates("ai_verified") + store.candidates("ai_rejected")
