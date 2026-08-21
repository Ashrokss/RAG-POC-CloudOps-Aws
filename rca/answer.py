"""
The read path, end to end: route, retrieve, generate, and open a gap when the
corpus could not answer.

Citations are resolved against what was actually retrieved rather than trusted
from the model's text: a tag naming a chunk that was never in context is not a
citation, it is a hallucination with punctuation.
"""

from __future__ import annotations

import re
import time

from rca import gaps
from rca.models import Answer, Chunk
from rca.providers import ChatModel
from rca.retrieve import Retriever
from rca.router import COVERAGE_FLOOR, classify
from rca.store import Store

SYSTEM_PROMPT = (
    "You are an SRE assistant answering questions about past cloud incidents. "
    "Everything you assert about what happened must come from the excerpts "
    "below. Each excerpt starts with a line like '[SOURCE: INC-2025-0101 · Root Cause]'; "
    "cite every factual claim inline with that chunk's own tag, e.g. "
    "[INC-2025-0101 · Root Cause]. The separator is the middle dot (·).\n\n"
    "If the excerpts do not contain enough information, reply with exactly "
    "'insufficient evidence in the retrieved context'. A question about an "
    "incident these excerpts do not cover is always that case - general "
    "knowledge about the technology is never a substitute for an incident record."
)

_CITATION_RE = re.compile(r"\[([^\]·]+)·([^\]]+)\]")


def format_context(chunks: list[Chunk]) -> str:
    return "\n\n".join(
        f"[SOURCE: {c.incident_id or c.doc_id} · {c.section}]\n{c.text}" for c in chunks
    )


def format_incident_index(rows: list[dict]) -> str:
    """The structured half of an aggregate answer. Complete by construction,
    which is the entire point: the model must not have to infer the corpus from
    whichever k chunks happened to surface."""
    lines = ["id | date | severity | services | detection_gap_min | duration_min | cost_usd | title"]
    for row in rows:
        lines.append(
            " | ".join(
                [
                    row["incident_id"] or "-",
                    (row["date"] or "")[:10],
                    row["severity"] or "-",
                    ",".join(row["services"]),
                    # "unknown", never 0 - a missing detection gap must not read
                    # as instant detection when the model ranks the column.
                    str(row["detection_gap_minutes"]) if row["detection_gap_minutes"] is not None else "unknown",
                    str(row["duration_minutes"]) if row["duration_minutes"] is not None else "unknown",
                    str(row["cost_usd"]) if row["cost_usd"] is not None else "unknown",
                    row["title"],
                ]
            )
        )
    return "### INCIDENT INDEX ###\n" + "\n".join(lines)


def resolve_citations(answer: str, chunks: list[Chunk]) -> list[str]:
    available = {f"{c.incident_id or c.doc_id} · {c.section}" for c in chunks}
    found: list[str] = []
    for match in _CITATION_RE.finditer(answer):
        tag = f"{match.group(1).strip()} · {match.group(2).strip()}"
        if tag in available and tag not in found:
            found.append(tag)
    return found


def ask(store: Store, retriever: Retriever, chat: ChatModel, question: str, k: int = 5) -> Answer:
    start = time.perf_counter()
    route = classify(question)
    result = retriever.hybrid(question, k)

    context = format_context(result.chunks)
    if route == "aggregate":
        services = gaps.question_services(question)
        context = format_incident_index(store.incidents(services)) + "\n\n" + context

    text = chat.complete(SYSTEM_PROMPT, f"{context}\n\n### QUESTION ###\n{question}")
    citations = resolve_citations(text, result.chunks)

    # Gap detection runs after generation so the model's own refusal counts as
    # a signal. On the aggregate route the coverage floor is disabled - the
    # index answers those by construction, so a low chunk score means nothing -
    # but refusal and unknown entities still open a gap there. "How many
    # connections does a Hyperplane ENI support" matches the aggregate regex
    # and is nothing of the sort; suppressing the whole detector on that route
    # meant the one question the corpus genuinely could not answer was the one
    # that never got recorded.
    gap = gaps.detect(
        store,
        question,
        result.coverage,
        text,
        citations=len(citations),
        floor=0.0 if route == "aggregate" else COVERAGE_FLOOR,
    )

    return Answer(
        question=question,
        route="gap" if gap else route,
        answer=text,
        citations=citations,
        retrieved_chunk_ids=[c.chunk_id for c in result.chunks],
        coverage=result.coverage,
        gap_id=gap.gap_id if gap else None,
        latency_ms=(time.perf_counter() - start) * 1000,
        model_id=chat.model_id,
    )
