"""
Moved to rag/chain/grounding.py: rag/chain/rag_chain.py's generate() now
calls check_grounding() directly to decide whether to retry a live answer,
not only to score one after the fact, and rag/ must not depend on eval/.
This thin re-export exists so any external caller still importing
eval.grounding does not silently break.
"""

from __future__ import annotations

from rag.chain.grounding import (
    INCIDENT_RE,
    check_grounding,
    count_by_kind,
)

__all__ = ["INCIDENT_RE", "check_grounding", "count_by_kind"]
