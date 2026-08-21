"""
Gap detection: three signals, not one.

A single similarity floor is not enough, and the offline embedder shows why -
a question about a Kubernetes etcd incident that this corpus has never heard
of scored *higher* than a legitimate question about a real one, because a hash
embedder rewards shared vocabulary ("incident", "how long") rather than shared
meaning. With a real embedding model the floor is meaningful; with any model
it is blunt. So it is one vote of three:

  unknown_entity  - the question names an INC-id, or a service, that the store
                    has never seen. Cheap, exact, and unambiguous.
  low_coverage    - top semantic score below the floor, and only when the
                    answer cited nothing. A resolved citation is direct
                    evidence that the corpus did contain something usable, and
                    it outranks a similarity number: after a knowledge card is
                    promoted, the question it answers must stop being reported
                    as a gap even if the embedder scores it modestly.
  refused         - the model itself said it had insufficient evidence. The
                    most trustworthy signal of the three, and the reason
                    refusal has to be a first-class outcome rather than a bug.

Two identical questions are one gap with a hit count. The count is the
prioritisation signal: research the gap ten people hit before the one that
someone asked once at midnight.
"""

from __future__ import annotations

import re
from typing import Optional

from rca.models import KnowledgeGap, stable_id
from rca.router import COVERAGE_FLOOR
from rca.store import Store
from rca.vocabulary import services_in

INCIDENT_RE = re.compile(r"INC-\d{4}-\d{4}(?:-[A-Z0-9-]+)?", re.IGNORECASE)
REFUSAL_PHRASE = "insufficient evidence in the retrieved context"


def _normalise(question: str) -> str:
    return " ".join(question.lower().split())


def unknown_entities(store: Store, question: str) -> list[str]:
    """Incident ids named in the question that the store does not contain. A
    question about INC-2025-0999 is a gap no matter how well it retrieves - and
    it retrieves well, because every real incident id looks alike."""
    known = {row["incident_id"] for row in store.incidents() if row["incident_id"]}
    known_upper = {i.upper() for i in known}
    return [m.upper() for m in INCIDENT_RE.findall(question) if m.upper() not in known_upper]


def detect(
    store: Store,
    question: str,
    coverage: float,
    answer: Optional[str] = None,
    citations: int = 0,
    floor: float = COVERAGE_FLOOR,
) -> Optional[KnowledgeGap]:
    missing = unknown_entities(store, question)
    if missing:
        # Exact, and it outranks everything: a question about an incident that
        # does not exist is a gap however well it retrieves, and it retrieves
        # well, because every incident id looks alike.
        reason = "unknown_entity"
    elif answer is not None and REFUSAL_PHRASE in answer.lower():
        reason = "refused"
    elif citations > 0:
        return None
    elif coverage < floor:
        reason = "low_coverage"
    else:
        return None

    gap = KnowledgeGap(
        # Keyed on the normalised question so the same ask from three people is
        # one row with hit_count 3, not three rows nobody prioritises.
        gap_id=stable_id(_normalise(question)),
        question=question,
        reason=reason,  # type: ignore[arg-type]
        best_score=coverage,
    )
    return store.record_gap(gap)


def question_services(question: str) -> list[str]:
    return services_in(question)
