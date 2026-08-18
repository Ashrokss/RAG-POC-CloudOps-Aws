"""
The two cases asserted here are the two the live bake-off actually produced -
a right incident with a wrong date, and the same cost figure counted twice
into a total that appears nowhere in the corpus. Both scored well under the
Jaccard judge, which is the whole reason this module exists.
"""

from __future__ import annotations

from langchain_core.documents import Document

from eval.grounding import check_grounding, count_by_kind


def _docs() -> list[Document]:
    return [
        Document(
            page_content=(
                "On 2025-10-02 the module bump replaced the scoped trust statement. "
                "The reconciler was delayed 84 minutes. Estimated unplanned spend was $20,700."
            ),
            metadata={
                "chunk_id": "chunk-1002",
                "doc_id": "doc-1002",
                "incident_id": "INC-2025-1002",
                "section": "Summary",
            },
        )
    ]


def test_grounded_answer_has_no_violations() -> None:
    answer = (
        "The trust policy regression began on 2 October and delayed the reconciler "
        "84 minutes, at an estimated $20,700 [INC-2025-1002 - Summary]."
    )

    assert check_grounding(answer, _docs()) == []


def test_wrong_date_beside_a_right_incident_is_caught() -> None:
    answer = "INC-2025-1002 occurred on 30 May and delayed the reconciler 84 minutes."

    violations = check_grounding(answer, _docs())

    assert count_by_kind(violations)["date"] == 1
    assert violations[0]["claim"] == "05-30"


def test_double_counted_total_is_caught_as_a_number_violation() -> None:
    answer = "INC-2025-1002 cost $20,700 and a further $20,700, totalling $41,400."

    counts = count_by_kind(check_grounding(answer, _docs()))

    # Dates stay clean; the invented total is the only unsupported figure.
    assert counts["date"] == 0
    assert counts["number"] == 1


def test_incident_with_no_retrieved_chunk_is_caught() -> None:
    answer = "INC-2025-0999 was caused by a database failover."

    violations = check_grounding(answer, _docs())

    assert count_by_kind(violations)["unretrieved_incident"] == 1


def test_incident_id_digits_do_not_ground_themselves() -> None:
    # "INC-2025-1002" must not donate 2025 and 1002 as supported figures, or an
    # answer could cite any number it liked as long as an id was nearby.
    answer = "INC-2025-1002 affected 1002 accounts."

    counts = count_by_kind(check_grounding(answer, _docs()))

    assert counts["number"] == 1
