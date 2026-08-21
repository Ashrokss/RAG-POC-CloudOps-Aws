"""
okf/failure-modes/*.md's incident_ids field says "these past incidents
exhibited this failure mode" - a forward declaration. A known_pattern match
asks the reverse question at query time: do the incidents retrieval just
surfaced for this new question collectively point at one already-catalogued
failure mode? If so, the corpus already has a human-curated answer for
exactly this recurrence - the failure mode plus its playbook - and asking
generate() to re-derive that from scratch is pure token spend on a question
this project has effectively already answered.

Requiring at least two distinct retrieved incidents to agree, not one, is
the whole precision mechanism. A failure mode with only one documented
incident (roughly half of them - cert-expiry, connection-draining,
port-exhaustion, ...) can never trigger this by construction, and a single
coincidental retrieval hit says nothing about whether a new question is
really the same pattern recurring. Two independent past incidents agreeing
is a real, if imperfect, signal; one is noise. A tie between two failure
modes each backed by 2+ incidents is exactly the ambiguous case a wrong
guess would be worst in, so it also falls back to no match rather than
picking arbitrarily.
"""

from __future__ import annotations

from functools import lru_cache
from pathlib import Path

from langchain_core.documents import Document

from rag.ingestion.loader import parse_frontmatter

# okf/ sits at the repo root, beside rag/ - resolved from __file__ for the
# same reason rag/ingestion/loader.py resolves _OKF_SERVICES_DIR this way.
_OKF_FAILURE_MODES_DIR = Path(__file__).resolve().parents[2] / "okf" / "failure-modes"
_RESERVED_FILENAMES = {"index.md", "log.md"}


@lru_cache(maxsize=1)
def _incident_failure_modes() -> dict[str, set[str]]:
    """incident_id -> the failure_mode ids that name it in their own
    incident_ids field - the inverse of what okf/failure-modes/*.md
    declares, built once rather than re-parsed per question."""
    mapping: dict[str, set[str]] = {}
    for path in sorted(_OKF_FAILURE_MODES_DIR.glob("*.md")):
        if path.name.lower() in _RESERVED_FILENAMES:
            continue
        metadata, _ = parse_frontmatter(path.read_text(encoding="utf-8"))
        failure_mode_id = str(metadata.get("id") or path.stem)
        for incident_id in metadata.get("incident_ids") or []:
            if isinstance(incident_id, str):
                mapping.setdefault(incident_id, set()).add(failure_mode_id)
    return mapping


def reset_failure_pattern_cache() -> None:
    # getattr-guarded like rag_chain.reset_corpus_cache's own cache resets:
    # tests monkeypatch _incident_failure_modes to a plain function (no
    # cache to clear), and teardown must not care which one it finds.
    clear = getattr(_incident_failure_modes, "cache_clear", None)
    if clear is not None:
        clear()


def match_known_pattern(docs: list[Document]) -> dict | None:
    """None if fewer than two distinct retrieved incidents agree on one
    failure mode - the common, safe-default case when a question is
    genuinely novel or only coincidentally touches one past incident.
    Otherwise {"failure_mode_id": ..., "matched_incident_ids": [...]}."""
    incident_modes = _incident_failure_modes()
    distinct_incidents = {doc.metadata["incident_id"] for doc in docs}

    votes: dict[str, set[str]] = {}
    for incident_id in distinct_incidents:
        for failure_mode_id in incident_modes.get(incident_id, ()):
            votes.setdefault(failure_mode_id, set()).add(incident_id)

    candidates = [(fm_id, matched) for fm_id, matched in votes.items() if len(matched) >= 2]
    if len(candidates) != 1:
        return None

    failure_mode_id, matched = candidates[0]
    return {"failure_mode_id": failure_mode_id, "matched_incident_ids": sorted(matched)}
