"""
match_known_pattern reads the real okf/failure-modes/*.md incident_ids
mapping, not a fixture - the same "use the real corpus" convention as
tests/test_routing.py, since the whole point is whether the curated
failure-mode catalogue actually recognizes a recurrence, not whether a
made-up substitute does.
"""

from __future__ import annotations

import pytest
from langchain_core.documents import Document

import rag.routing.failure_pattern as failure_pattern_module
from rag.routing.failure_pattern import match_known_pattern


def _doc(incident_id: str) -> Document:
    return Document(
        page_content="...",
        metadata={
            "chunk_id": f"chunk-{incident_id}",
            "doc_id": f"doc-{incident_id}",
            "incident_id": incident_id,
            "section": "Root Cause",
        },
    )


def test_two_agreeing_incidents_match_a_known_failure_mode() -> None:
    # okf/failure-modes/quota-exhaustion.md names all three of these.
    docs = [_doc("INC-2025-0201"), _doc("INC-2025-0902"), _doc("INC-2025-1001")]

    match = match_known_pattern(docs)

    assert match is not None
    assert match["failure_mode_id"] == "quota-exhaustion"
    assert set(match["matched_incident_ids"]) == {"INC-2025-0201", "INC-2025-0902", "INC-2025-1001"}


def test_exactly_two_incidents_is_enough_to_match() -> None:
    # okf/failure-modes/health-check-flapping.md's exact incident_ids list -
    # the precise boundary of the ">= 2" threshold, not a 3-incident case
    # where a looser rule would also happen to pass.
    docs = [_doc("INC-2025-0402"), _doc("INC-2025-0802")]

    match = match_known_pattern(docs)

    assert match is not None
    assert match["failure_mode_id"] == "health-check-flapping"


def test_a_single_incident_is_not_a_pattern() -> None:
    # port-exhaustion has exactly one documented incident - by construction
    # this can never match, coincidental single-incident retrieval hits
    # included. (INC-2025-1001 also appears under quota-exhaustion, but one
    # distinct incident can never reach the >= 2 threshold for either.)
    docs = [_doc("INC-2025-1001")]

    assert match_known_pattern(docs) is None


def test_incidents_sharing_no_failure_mode_do_not_match() -> None:
    # connection-pool-exhaustion (INC-2025-0101) and cert-expiry
    # (INC-2025-0801) - two real, unrelated failure modes.
    docs = [_doc("INC-2025-0101"), _doc("INC-2025-0801")]

    assert match_known_pattern(docs) is None


def test_unknown_incident_ids_do_not_crash() -> None:
    docs = [_doc("INC-9999-9999"), _doc("INC-8888-8888")]

    assert match_known_pattern(docs) is None


def test_tied_failure_modes_fall_back_to_no_match(monkeypatch: pytest.MonkeyPatch) -> None:
    # Two failure modes each backed by 2+ retrieved incidents is exactly the
    # ambiguous case a wrong guess would be worst in.
    monkeypatch.setattr(
        failure_pattern_module,
        "_incident_failure_modes",
        lambda: {
            "INC-A": {"mode-x"},
            "INC-B": {"mode-x"},
            "INC-C": {"mode-y"},
            "INC-D": {"mode-y"},
        },
    )
    docs = [_doc("INC-A"), _doc("INC-B"), _doc("INC-C"), _doc("INC-D")]

    assert match_known_pattern(docs) is None
