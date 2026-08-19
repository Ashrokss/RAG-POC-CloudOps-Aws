"""
Top-k retrieval structurally cannot answer "how many", "list every", "which
is longest" or "total these" - the model only ever sees k chunks, so a
complete answer over 25 incidents is not something a better reranker fixes.
A live bake-off confirmed it: the enumerate/rank/total questions were the
ones every strategy got wrong, at every k.

Intent classification is a regex over the question, not an LLM call: the
trigger vocabulary is small and closed, and paying a model round-trip (and a
second failure mode) to decide which path to take is worse than the
occasional over-trigger. Over-triggering is the cheap direction anyway - the
aggregate path still runs normal retrieval and still cites chunk text, it
just also hands over the incident index.

Service filtering reuses the okf/services alias map, so "every Lambda
incident" filters on the canonical id that ingestion already normalised the
frontmatter to - which is exactly why the controlled vocabulary had to land
before this did.

blast_radius is a third, later addition answering a question neither of the
above two can: "what else breaks if X is down" needs the depends_on graph
curated in okf/services/*.md, not incident text or an incident-level index.
It is checked before _AGGREGATE_RE - "what depends on RDS" would otherwise
never fire the aggregate regex anyway, but "list everything that depends on
RDS" contains both "list every..." and "depends on", and the dependency
graph (not the incident index) is the actually-correct source for that
question. blast_radius is a hint, not a commitment: retrieve_for_question
downgrades it back to retrieval if question_services() cannot resolve a
service to compute the graph against, the same "over-trigger is cheap"
tolerance _AGGREGATE_RE already relies on.
"""

from __future__ import annotations

import re
from typing import Literal

from rag.ingestion.loader import service_alias_map

Route = Literal["retrieval", "aggregate", "blast_radius"]

_BLAST_RADIUS_RE = re.compile(
    r"\b(depends? on|dependent on|dependenc(?:y|ies) of|relies? on|reliant on|"
    r"downstream of|downstream impact|blast radius|breaks? if|fails? if|affected if)\b",
    re.IGNORECASE,
)

# "between X and Y" was in the first draft of this list and is gone on
# evidence: it caught no adversarial question that "longest"/"every" did not
# already catch, and it did catch a golden question ("the key difference
# between the two Lambda incidents, INC-2025-0201 and INC-2025-0202") that is
# an ordinary two-document comparison, not an aggregate.
_AGGREGATE_RE = re.compile(
    r"\b(how many|count|list all|list every|every|all of the|total|totals|"
    r"longest|shortest|most|fewest|average|across all|each of)\b",
    re.IGNORECASE,
)


def classify(question: str) -> Route:
    if _BLAST_RADIUS_RE.search(question):
        return "blast_radius"
    return "aggregate" if _AGGREGATE_RE.search(question) else "retrieval"


def question_services(question: str) -> list[str]:
    """Canonical service ids named in the question, longest alias first so
    "API Gateway" wins over a bare "api" substring."""
    lowered = question.lower()
    found: list[str] = []
    for alias, service_id in sorted(service_alias_map().items(), key=lambda kv: -len(kv[0])):
        if service_id in found:
            continue
        if re.search(rf"(?<![\w-]){re.escape(alias)}(?![\w-])", lowered):
            found.append(service_id)
    return found
