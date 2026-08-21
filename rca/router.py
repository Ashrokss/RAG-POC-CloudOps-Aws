"""
Three routes, decided before retrieval runs.

`aggregate` exists because top-k structurally cannot answer "how many", "list
every", "longest" or "total" - the model only ever sees k chunks, so no
reranker fixes it. `gap` exists because a system that always answers can never
learn what it does not know; the refusal is the signal the learning loop
subscribes to.

Classification is a regex, not a model call. The trigger vocabulary is small
and closed, and paying a round-trip - plus a second failure mode - to decide
which path to take is worse than the occasional over-trigger. Over-triggering
is the cheap direction: the aggregate route still retrieves and still cites,
it just also hands over the structured index.
"""

from __future__ import annotations

import re

from rca.models import Route

AGGREGATE_RE = re.compile(
    r"\b(how many|count|list all|list every|every|all of the|total|totals|longest|"
    r"shortest|most|fewest|average|across all|each of)\b",
    re.IGNORECASE,
)

# Below this top-cosine score, the corpus is judged not to contain an answer.
# Tuned to fire on genuinely absent subjects while leaving paraphrased but
# present questions alone; it is a threshold on a blunt signal, so it is
# deliberately conservative and every firing is logged for review.
COVERAGE_FLOOR = 0.35


def classify(question: str) -> Route:
    return "aggregate" if AGGREGATE_RE.search(question) else "retrieval"


def is_gap(coverage: float, floor: float = COVERAGE_FLOOR) -> bool:
    return coverage < floor
