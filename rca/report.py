"""
The RCA generator: a typed object, not an essay.

Prose hides its own gaps. A fluent paragraph reads the same whether the model
had evidence for a claim or invented it, so the report is assembled field by
field, each field asking only for what its own retrieved evidence supports.
Two properties fall out of that:

  evidence_map       - citations per field, so coverage is measurable per
                       claim rather than per document
  unsupported_fields - fields the corpus could not support, stated plainly
                       instead of smoothed over

A generated report re-enters the pipeline as a candidate. The system does not
trust its own output merely because it produced it.
"""

from __future__ import annotations

from rca.answer import format_context, resolve_citations
from rca.models import FiveWhy, RCAReport
from rca.providers import ChatModel
from rca.retrieve import Retriever
from rca.store import Store

SYSTEM_PROMPT = (
    "You are writing one section of a root-cause analysis from incident excerpts. "
    "Use only what the excerpts state. Cite each claim with its chunk tag, e.g. "
    "[INC-2025-0101 · Root Cause]. If the excerpts do not support this section, "
    "reply with exactly 'NOT SUPPORTED' and nothing else."
)

NOT_SUPPORTED = "NOT SUPPORTED"

_SECTIONS = {
    "summary": "One paragraph: what happened, when, and who it affected.",
    "impact": "The measured impact: duration, error rates, customers, cost.",
    "root_cause": "The single root cause. Not the trigger - the reason the trigger caused harm.",
    "detection": "How it was detected, and how long after impact began.",
}
_LIST_SECTIONS = {
    "timeline": "The timeline, one event per line, in order, each with its timestamp.",
    "contributing_factors": "Contributing factors, one per line. Not the root cause itself.",
    "mitigation": "What was done to mitigate, one action per line.",
    "action_items": "Follow-up action items, one per line.",
}


def _ask_section(chat: ChatModel, context: str, instruction: str) -> str:
    return chat.complete(SYSTEM_PROMPT, f"{context}\n\n### SECTION ###\n{instruction}").strip()


def _five_whys(chat: ChatModel, context: str, root_cause: str, chunks) -> list[FiveWhy]:
    """Five whys as a chain of typed steps, each citing its own evidence. A
    single blob of prose lets an unsupported link hide between two supported
    ones."""
    if not root_cause or root_cause == NOT_SUPPORTED:
        return []
    raw = _ask_section(
        chat,
        context,
        "Give the why-chain leading to this root cause, at most 5 steps, one per line, "
        f"each formatted 'why -> because'. Root cause: {root_cause}",
    )
    chain: list[FiveWhy] = []
    for line in raw.splitlines():
        if "->" not in line:
            continue
        why, because = line.split("->", 1)
        chain.append(
            FiveWhy(
                why=why.strip(" -*0123456789."),
                because=because.strip(),
                citations=resolve_citations(because, chunks),
            )
        )
    return chain[:5]


def generate_rca(
    store: Store, retriever: Retriever, chat: ChatModel, incident_id: str, k: int = 8
) -> RCAReport:
    hits = retriever.hybrid(incident_id, k * 2).chunks
    # Retrieval is a filter here, not a ranker: a report about one incident must
    # never be assembled from a neighbouring incident's text.
    chunks = [c for c in hits if c.incident_id == incident_id][:k]
    context = format_context(chunks)

    report = RCAReport(incident_id=incident_id)
    if not chunks:
        report.unsupported_fields = sorted({*_SECTIONS, *_LIST_SECTIONS, "five_whys"})
        return report

    for field, instruction in _SECTIONS.items():
        text = _ask_section(chat, context, instruction)
        if NOT_SUPPORTED in text:
            report.unsupported_fields.append(field)
            continue
        setattr(report, field, text)
        # Only record a field in evidence_map when it actually cites something -
        # an empty list there reads as "checked and fine" in every consumer.
        if citations := resolve_citations(text, chunks):
            report.evidence_map[field] = citations

    for field, instruction in _LIST_SECTIONS.items():
        text = _ask_section(chat, context, instruction)
        if NOT_SUPPORTED in text:
            report.unsupported_fields.append(field)
            continue
        items = [line.strip(" -*") for line in text.splitlines() if line.strip()]
        setattr(report, field, items)
        if citations := resolve_citations(text, chunks):
            report.evidence_map[field] = citations

    report.five_whys = _five_whys(chat, context, report.root_cause, chunks)
    if not report.five_whys:
        report.unsupported_fields.append("five_whys")

    services = list({s for c in chunks for s in c.services})
    report.similar_incidents = [
        i for i in retriever.similar_incidents(report.summary or incident_id, 4, services)
        if i != incident_id
    ][:3]

    # Fields with text but no resolvable citation are worse than empty ones:
    # they read as evidenced and are not.
    for field in [*_SECTIONS, *_LIST_SECTIONS]:
        if getattr(report, field) and not report.evidence_map.get(field):
            report.unsupported_fields.append(field)

    report.unsupported_fields = sorted(set(report.unsupported_fields))
    return report


def render_markdown(report: RCAReport) -> str:
    lines = [f"# RCA {report.incident_id}", ""]
    if report.summary:
        lines += ["## Summary", "", report.summary, ""]
    if report.timeline:
        lines += ["## Timeline", ""] + [f"- {t}" for t in report.timeline] + [""]
    if report.impact:
        lines += ["## Impact", "", report.impact, ""]
    if report.root_cause:
        lines += ["## Root Cause", "", report.root_cause, ""]
    if report.five_whys:
        lines += ["## Five Whys", ""]
        for i, step in enumerate(report.five_whys, 1):
            lines.append(f"{i}. **{step.why}** -> {step.because}")
        lines.append("")
    for title, items in (
        ("Contributing Factors", report.contributing_factors),
        ("Mitigation", report.mitigation),
        ("Action Items", report.action_items),
    ):
        if items:
            lines += [f"## {title}", ""] + [f"- {i}" for i in items] + [""]
    if report.detection:
        lines += ["## Detection", "", report.detection, ""]
    if report.similar_incidents:
        lines += ["## Similar Incidents", ""] + [f"- {i}" for i in report.similar_incidents] + [""]
    if report.unsupported_fields:
        lines += [
            "## Not supported by the corpus",
            "",
            "These sections had no citable evidence and were left empty rather than filled in:",
            "",
        ] + [f"- {f}" for f in report.unsupported_fields] + [""]
    return "\n".join(lines)
