"""
The research agent: turn an open gap into a candidate card.

Search is injected, not hardcoded. Live web search is the single most
expensive component in this design - roughly twenty times the cost of the LLM
call it feeds - so it belongs behind an interface that can be a fixture in
tests, a vendor-doc mirror offline, and a paid API in production, chosen by
configuration rather than by editing this file.

HARD BOUNDARY: the query sent outward is a sanitised symptom, never retrieved
text. Incident documents contain account ids, bucket names, internal service
names and customer counts. `sanitise_query` is the only thing that may
construct an outbound query, and it is tested, because "we'll remember not to
paste chunks into the search box" is not a control.
"""

from __future__ import annotations

import re
from typing import Callable, Protocol

from rca.models import CandidateCard, Evidence, KnowledgeGap, stable_id
from rca.store import Store
from rca.vocabulary import services_in

# Things that must never leave the building, in rough order of how bad it is.
_ACCOUNT_RE = re.compile(r"\b\d{12}\b")
_ARN_RE = re.compile(r"arn:aws:[^\s]+")
_IP_RE = re.compile(r"\b\d{1,3}(?:\.\d{1,3}){3}\b")
_SUBNET_RE = re.compile(r"\b(?:subnet|vpc|sg|i|vol|eni)-[0-9a-f]{8,}\b", re.IGNORECASE)
_HOST_RE = re.compile(r"\b[\w.-]+\.(?:amazonaws\.com|internal|local|azurewebsites\.net)\b")
_INTERNAL_ID_RE = re.compile(r"\bINC-\d{4}-\d{4}(?:-[A-Z0-9-]+)?\b", re.IGNORECASE)
_EMAIL_RE = re.compile(r"\b[\w.+-]+@[\w-]+\.[\w.]+\b")

_REDACTIONS = (
    (_ARN_RE, ""),
    (_HOST_RE, ""),
    (_EMAIL_RE, ""),
    (_ACCOUNT_RE, ""),
    (_IP_RE, ""),
    (_SUBNET_RE, ""),
    (_INTERNAL_ID_RE, ""),
)


def sanitise_query(text: str) -> str:
    """Strip anything that identifies this organisation's infrastructure. What
    survives is the technology and the symptom, which is all an external search
    needs to be useful."""
    out = text
    for pattern, replacement in _REDACTIONS:
        out = pattern.sub(replacement, out)
    return " ".join(out.split())


class SearchResult(Protocol):
    url: str
    title: str
    text: str


SearchFn = Callable[[str, int], list[dict]]


def offline_search(query: str, limit: int = 3) -> list[dict]:
    """No network. Returns nothing, which makes the gap visible in the queue
    without inventing an answer - the correct offline behaviour for a component
    whose entire job is to fetch facts it does not have."""
    return []


_AUTHORITY_BY_HOST = {
    "docs.aws.amazon.com": "vendor_doc",
    "aws.amazon.com": "vendor_doc",
    "learn.microsoft.com": "vendor_doc",
    "cloud.google.com": "vendor_doc",
    "health.aws.amazon.com": "official_postmortem",
    "blog.cloudflare.com": "official_postmortem",
    "about.gitlab.com": "official_postmortem",
    "engineering.fb.com": "official_postmortem",
}


def authority_of(url: str) -> str:
    for host, tier in _AUTHORITY_BY_HOST.items():
        if host in url:
            return tier
    return "community" if url.startswith("http") else "unknown"


def research(
    store: Store, gap: KnowledgeGap, search: SearchFn = offline_search, limit: int = 3
) -> CandidateCard | None:
    query = sanitise_query(gap.question)
    results = search(query, limit)
    if not results:
        return None

    evidence = [
        Evidence(
            url=r["url"],
            title=r.get("title", ""),
            # The quote is what the verifier re-checks against the fetched
            # page, so it must be copied verbatim, never summarised here.
            quote=r["text"].strip()[:400],
            authority=authority_of(r["url"]),  # type: ignore[arg-type]
        )
        for r in results
    ]

    card = CandidateCard(
        candidate_id=stable_id("candidate", gap.gap_id, evidence[0].url),
        gap_id=gap.gap_id,
        claim=evidence[0].quote,
        applies_to=services_in(gap.question),
        evidence=evidence,
        confidence=0.0,  # set by the verifier; an author never scores itself
        status="draft",
    )
    store.save_candidate(card)
    store.set_gap_status(gap.gap_id, "candidate")
    store.audit("research", "candidate_drafted", card.candidate_id, query[:200])
    return card
