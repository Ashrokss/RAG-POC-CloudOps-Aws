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

import frontmatter

from rca import failure_pattern, gaps
from rca.models import Answer, Chunk
from rca.providers import ChatModel
from rca.retrieve import Retriever
from rca.router import COVERAGE_FLOOR, classify
from rca.store import Store

SYSTEM_PROMPT = (
    "You are an SRE assistant. Everything you assert must come from the excerpts "
    "below. Each excerpt starts with a line like "
    "'[SOURCE: INC-2025-0101 · Root Cause]'; cite every factual claim inline with "
    "that chunk's own tag, e.g. [INC-2025-0101 · Root Cause]. The separator is "
    "the middle dot (·).\n\n"
    "Excerpts come in two kinds and both are usable:\n"
    "- INCIDENT RECORDS - what happened in this organisation's own incidents.\n"
    "- REFERENCE MATERIAL - vendor documentation that a human reviewed and "
    "approved into the knowledge base. Marked '(reference)' on its SOURCE line. "
    "Use it to answer how a service behaves or what a limit is, and cite it the "
    "same way.\n\n"
    "If the excerpts do not contain enough information, reply with exactly "
    "'insufficient evidence in the retrieved context'. A question about an "
    "incident these excerpts do not cover is always that case: reference "
    "material explains how technology behaves and is never a substitute for an "
    "incident record about what actually happened here."
)

_CITATION_RE = re.compile(r"\[([^\]·]+)·([^\]]+)\]")


def format_context(chunks: list[Chunk]) -> str:
    """Reference excerpts are marked on their SOURCE line. Without the marker a
    promoted vendor-doc card looked like an incident record with an unfamiliar
    id, and the model refused to use it: retrieval surfaced the approved answer
    in the top three chunks and the prompt would not let it be spent."""
    parts = []
    for c in chunks:
        marker = " (reference)" if c.source_tier == "reference" else ""
        parts.append(f"[SOURCE: {c.cite_key} · {c.section}]{marker}\n{c.text}")
    return "\n\n".join(parts)


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
    available = {f"{c.cite_key} · {c.section}" for c in chunks}
    found: list[str] = []
    for match in _CITATION_RE.finditer(answer):
        tag = f"{match.group(1).strip()} · {match.group(2).strip()}"
        if tag in available and tag not in found:
            found.append(tag)
    return found


def _extract_section(body: str, header: str) -> str:
    """Body text under '## {header}', up to the next '## ' heading or the
    end of the file. Simple substring splitting, not a markdown parser - safe
    because okf/failure-modes/*.md and okf/playbooks/*.md both use a small,
    fixed set of headers this project itself authored, not arbitrary
    user-supplied markdown."""
    marker = f"## {header}"
    start = body.find(marker)
    if start == -1:
        return ""
    start += len(marker)
    next_header = body.find("\n## ", start)
    section = body[start:next_header] if next_header != -1 else body[start:]
    return section.strip()


def render_known_pattern_answer(match: dict, chunks: list[Chunk]) -> tuple[str, list[str]]:
    """ask()'s zero-chat-model counterpart: the corpus already has a
    human-curated answer for this recurring failure - the failure mode plus
    its playbook - so this reads and composes those two already-written
    files instead of asking the model to re-derive the same analysis it (or
    a prior run of it) already gave once. Only called when
    failure_pattern.match_known_pattern already found a match, so the
    matched okf/ files are expected to exist."""
    failure_mode_id = match["failure_mode_id"]
    matched_incident_ids = set(match["matched_incident_ids"])

    fm_metadata, fm_body = frontmatter.parse(
        (failure_pattern.FAILURE_MODES_DIR / f"{failure_mode_id}.md").read_text(encoding="utf-8")
    )
    _, pb_body = frontmatter.parse(
        (failure_pattern.PLAYBOOKS_DIR / f"{failure_mode_id}.md").read_text(encoding="utf-8")
    )

    answer = (
        f"Recognized recurring pattern: **{fm_metadata.get('name', failure_mode_id)}** - matched "
        f"against previously documented incidents {', '.join(sorted(matched_incident_ids))}, which "
        f"the corpus already catalogues under this failure mode. This is the existing curated "
        f"playbook, not a fresh analysis of this specific occurrence; if it doesn't actually fit, "
        f"ask again with more specific detail to force a full analysis.\n\n"
        f"**What it is**\n{_extract_section(fm_body, 'What it is')}\n\n"
        f"**When you see this**\n{_extract_section(pb_body, 'When you see this')}\n\n"
        f"**Mitigate**\n{_extract_section(pb_body, 'Mitigate')}\n\n"
        f"**Prevent**\n{_extract_section(pb_body, 'Prevent')}"
    )

    citations: list[str] = []
    seen: set[str] = set()
    for c in chunks:
        if c.incident_id not in matched_incident_ids:
            continue
        tag = f"{c.cite_key} · {c.section}"
        if tag in seen:
            continue
        seen.add(tag)
        citations.append(tag)

    return answer, citations


def ask(store: Store, retriever: Retriever, chat: ChatModel, question: str, k: int = 5) -> Answer:
    start = time.perf_counter()
    route = classify(question)
    result = retriever.hybrid(question, k)

    # known_pattern can only be decided from what got retrieved, never from
    # the question text alone (see rca/failure_pattern.py), so it is checked
    # here rather than by classify() - and only for an otherwise ordinary
    # question, not one already headed for the incident index.
    if route == "retrieval":
        match = failure_pattern.match_known_pattern(result.chunks)
        if match:
            answer_text, citations = render_known_pattern_answer(match, result.chunks)
            return Answer(
                question=question,
                route="known_pattern",
                answer=answer_text,
                citations=citations,
                retrieved_chunk_ids=[c.chunk_id for c in result.chunks],
                coverage=result.coverage,
                gap_id=None,
                latency_ms=(time.perf_counter() - start) * 1000,
                model_id="none (matched known pattern)",
            )

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
