"""
Adversarial verification. The verifier's job is to fail cards, not bless them.

Three rules make this more than theatre:

  1. It is not the author. Different prompt, ideally a different model, and it
     never sees the research agent's reasoning - only the claim and the
     sources.
  2. It votes, and it defaults to reject. N independent verdicts, majority
     required, uncertainty counts as refusal.
  3. Its cheapest check is mechanical, not model-based: does each quote appear
     verbatim in the page it cites? A model asked "is this well supported?"
     will say yes to almost anything; string containment will not.

"approved" here means fit for a human to look at. It is never permission to
publish - only rca/review.py can promote, and only a person can call it.
"""

from __future__ import annotations

from typing import Callable, Optional

from rca.models import CandidateCard, Verdict
from rca.providers import ChatModel
from rca.store import Store

FetchFn = Callable[[str], str]

_AUTHORITY_WEIGHT = {"vendor_doc": 1.0, "official_postmortem": 0.8, "community": 0.4, "unknown": 0.1}

VERIFIER_PROMPT = (
    "You are checking whether a claim is supported by its cited sources. Try to "
    "REFUTE it. Answer REFUTED if the sources do not clearly state the claim, if "
    "they are ambiguous, or if you are unsure. Answer SUPPORTED only when a "
    "source states it plainly. Reply with one word: SUPPORTED or REFUTED."
)


def quotes_verified(card: CandidateCard, fetch: Optional[FetchFn]) -> tuple[int, int]:
    """Verbatim containment, whitespace-normalised. Cheap, and it catches the
    failure mode a language model is worst at spotting: a quote that was
    paraphrased into existence."""
    if fetch is None:
        return 0, len(card.evidence)
    verified = 0
    for item in card.evidence:
        try:
            page = " ".join(fetch(item.url).split()).lower()
        except Exception:
            continue
        if " ".join(item.quote.split()).lower() in page:
            verified += 1
    return verified, len(card.evidence)


def find_conflicts(store: Store, card: CandidateCard) -> list[str]:
    """A card that contradicts existing knowledge is not auto-rejected - it may
    be the correction. It is flagged so a human resolves it, because silently
    accepting either side is how a knowledge base starts disagreeing with
    itself."""
    conflicts: list[str] = []
    claim = card.claim.strip().lower()

    if claim in {c.claim.strip().lower() for c in store.candidates("promoted")}:
        conflicts.append("duplicate of an already-promoted card")

    # A card that contradicts an incident record about the same service is the
    # interesting case: the incident is what actually happened here, so either
    # the card is wrong or it is a correction worth making deliberately.
    # ponytail: lexical negation probe only - an NLI model is the upgrade path
    # if this misses too much.
    negations = [f"not {w}" for w in ("supported", "possible", "allowed", "required")]
    for service in card.applies_to:
        for row in store.incidents([service]):
            body = (row["body"] or "").lower()
            if any(neg in claim and neg.split()[1] in body for neg in negations):
                conflicts.append(f"possible contradiction with {row['incident_id']}")
                break
    return conflicts


def verify(
    store: Store,
    card: CandidateCard,
    chat: ChatModel,
    fetch: Optional[FetchFn] = None,
    voters: int = 3,
) -> Verdict:
    verified, total = quotes_verified(card, fetch)
    authority = max(
        (_AUTHORITY_WEIGHT.get(e.authority, 0.1) for e in card.evidence), default=0.0
    )
    conflicts = find_conflicts(store, card)

    votes_for = 0
    sources = "\n\n".join(f"[{e.url}]\n{e.quote}" for e in card.evidence)
    for _ in range(voters):
        reply = chat.complete(VERIFIER_PROMPT, f"CLAIM:\n{card.claim}\n\nSOURCES:\n{sources}")
        votes_for += int("SUPPORTED" in reply.upper() and "REFUTED" not in reply.upper())

    notes: list[str] = []
    if total and verified < total:
        notes.append(f"{total - verified} of {total} quotes not found verbatim in their source")
    if authority < 0.5:
        notes.append("no vendor or official-postmortem source")
    if conflicts:
        notes.append("conflicts with existing knowledge")

    approved = (
        total > 0
        and verified == total
        and authority >= 0.5
        and not conflicts
        and votes_for * 2 > voters
    )

    verdict = Verdict(
        approved=approved,
        quotes_verified=verified,
        quotes_total=total,
        authority_score=authority,
        conflicts=conflicts,
        votes_for=votes_for,
        votes_total=voters,
        notes=notes,
    )
    card.verdict = verdict
    card.status = "ai_verified" if approved else "ai_rejected"
    card.confidence = round(
        (verified / total if total else 0) * 0.5 + authority * 0.3 + (votes_for / voters) * 0.2, 3
    )
    store.save_candidate(card)
    store.audit(
        "verifier",
        "candidate_" + card.status,
        card.candidate_id,
        f"quotes={verified}/{total} authority={authority} votes={votes_for}/{voters}",
    )
    return verdict
