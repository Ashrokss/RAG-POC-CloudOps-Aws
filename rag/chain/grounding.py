"""
Token overlap against a reference summary cannot see a wrong date attached to
a right incident: a live bake-off produced an answer that dated INC-2025-1002
to 30 May and called it a concurrency config change (it is 1-2 Oct, an IAM
trust-policy regression), and that answer scored fine under Jaccard because
every word in it was plausible vocabulary for this corpus.

So this checks the one thing overlap cannot: for every sentence that names an
incident, each date and each figure in that sentence must actually appear in
the retrieved chunk text for that same incident. It is a grounding check, not
a correctness check - it says "the model asserted something next to an
incident id that the incident's own text does not contain", which is exactly
the shape of a confidently-wrong RCA answer.

Numbers are reported separately from dates because a legitimate aggregate
answer computes figures that appear nowhere in the source (a total is the
whole point of the question), while a date is always quoted, never derived. A
strategy being promoted on an enumeration question should have zero date
violations; number violations need a human to look at the arithmetic.

Deliberate ceiling: this is lexical, sentence-scoped, and knows nothing about
paraphrase - "47 minutes" grounds against "47", but "just under an hour" does
not ground against anything. It is a floor on hallucination, not a ceiling on
truth. It also cannot catch the wrong-but-real-figure case - a document that
states both a 47-minute detection gap and a 4h12m staleness window, quoted
against the wrong one - since both figures genuinely appear somewhere in that
incident's text. # ponytail: lexical matcher; an NLI or claim-extraction
model is the upgrade path if the false-positive rate on prose answers gets
annoying, or if that adjacent-figure case needs catching too.

Lives in rag/chain/, not eval/, because rag/chain/rag_chain.py's generate()
calls check_grounding() directly to decide whether to retry a live answer,
not only to score one after the fact - the same reason
check_dependency_completeness lives in rag/routing/dependency_graph.py
rather than eval/. eval/answer_quality.py imports from here instead.
"""

from __future__ import annotations

import re
from collections.abc import Sequence

from langchain_core.documents import Document

# Matches both the synthetic ids (INC-2025-0101) and the real-incident ids
# that carry a trailing slug (INC-2017-0228-S3-USEAST1).
INCIDENT_RE = re.compile(r"INC-\d{4}-\d{4}(?:-[A-Z0-9]+(?:-[A-Z0-9]+)*)?")

_SENTENCE_SPLIT_RE = re.compile(r"(?<=[.!?])\s+|\n+")
_ISO_DATE_RE = re.compile(r"\b(\d{4})-(\d{2})-(\d{2})\b")
_NUMBER_RE = re.compile(r"\d[\d,]*(?:\.\d+)?")

_MONTHS = {
    "jan": 1, "feb": 2, "mar": 3, "apr": 4, "may": 5, "jun": 6,
    "jul": 7, "aug": 8, "sep": 9, "oct": 10, "nov": 11, "dec": 12,
}
_MONTH_ALTERNATION = "|".join(_MONTHS)
_TEXT_DATE_RE = re.compile(
    rf"\b(\d{{1,2}})\s+({_MONTH_ALTERNATION})[a-z]*\b|\b({_MONTH_ALTERNATION})[a-z]*\s+(\d{{1,2}})\b",
    re.IGNORECASE,
)


def _dates(text: str) -> set[tuple[int, int]]:
    """(month, day) pairs. Year is dropped on purpose: the corpus spans 2017 to
    2026 and an answer that writes "2 October" without a year is not making a
    claim about the year."""
    found = {(int(m), int(d)) for _, m, d in _ISO_DATE_RE.findall(text)}
    for day_first, month_name_1, month_name_2, day_last in _TEXT_DATE_RE.findall(text):
        if month_name_1:
            found.add((_MONTHS[month_name_1[:3].lower()], int(day_first)))
        else:
            found.add((_MONTHS[month_name_2[:3].lower()], int(day_last)))
    return found


def _numbers(text: str) -> set[str]:
    # Incident ids are stripped first or every id donates its own digits
    # ("INC-2025-1002" -> 2025, 1002) and grounds itself. Dates go too: the "2"
    # in "2 October" is already checked as a date, and counting it again as a
    # figure reports one wrong date as two violations.
    stripped = _TEXT_DATE_RE.sub(" ", _ISO_DATE_RE.sub(" ", INCIDENT_RE.sub(" ", text)))
    return {_normalise_number(match) for match in _NUMBER_RE.findall(stripped)}


def _normalise_number(raw: str) -> str:
    """"$20,700" and "20700" are the same figure; "4.50" and "4.5" are too.
    Trailing zeros are only ever stripped after a decimal point - doing it
    unconditionally would turn 61000 into 61."""
    value = raw.replace(",", "")
    if "." in value:
        value = value.rstrip("0").rstrip(".")
    return value or "0"


def _source_text(docs: Sequence[Document], incident_ids: set[str]) -> str:
    return "\n".join(doc.page_content for doc in docs if doc.metadata["incident_id"] in incident_ids)


def check_grounding(answer: str, docs: Sequence[Document]) -> list[dict]:
    """Violations, one dict per unsupported claim. Empty list = every date and
    figure stated beside an incident id appears in that incident's text."""
    retrieved_ids = {doc.metadata["incident_id"] for doc in docs}
    violations: list[dict] = []

    for sentence in _SENTENCE_SPLIT_RE.split(answer):
        mentioned = set(INCIDENT_RE.findall(sentence))
        if not mentioned:
            continue

        missing = mentioned - retrieved_ids
        for incident_id in sorted(missing):
            violations.append(
                {
                    "kind": "unretrieved_incident",
                    "incident_ids": [incident_id],
                    "claim": incident_id,
                    "sentence": sentence.strip()[:200],
                }
            )

        grounded = mentioned & retrieved_ids
        if not grounded:
            continue

        source = _source_text(docs, grounded)
        source_dates, source_numbers = _dates(source), _numbers(source)

        for month, day in sorted(_dates(sentence) - source_dates):
            violations.append(
                {
                    "kind": "date",
                    "incident_ids": sorted(grounded),
                    "claim": f"{month:02d}-{day:02d}",
                    "sentence": sentence.strip()[:200],
                }
            )

        for number in sorted(_numbers(sentence) - source_numbers):
            violations.append(
                {
                    "kind": "number",
                    "incident_ids": sorted(grounded),
                    "claim": number,
                    "sentence": sentence.strip()[:200],
                }
            )

    return violations


def count_by_kind(violations: list[dict]) -> dict[str, int]:
    counts = {"date": 0, "number": 0, "unretrieved_incident": 0}
    for violation in violations:
        counts[violation["kind"]] += 1
    return counts
