"""
Covers the adversarial scoring path end to end: the schema still loads the
89-question golden file (86 original, 2 blast_radius, 1 known_pattern) with
no adversarial fields leaking onto ordinary questions, the new optional fields
default to inert values, and each adversarial sub-score fails the answer it
is supposed to fail. The judge is exercised on hand-written answers rather than on
MockChatModel output because the mock cannot refuse - it quotes retrieved
chunks by construction - so a mock-driven assertion would measure the mock,
not the scoring.
"""

from __future__ import annotations

from pathlib import Path

from langchain_core.documents import Document

from eval.answer_quality import adversarial_judge
from eval.golden_schema import load_golden_questions
from rag.models import Citation, GoldenQuestion

_GOLDEN_PATH = Path("data/golden_qa/golden_qa.yaml")
_ADVERSARIAL_PATH = Path("data/golden_qa/adversarial_qa.yaml")


def _docs() -> list[Document]:
    return [
        Document(
            page_content="An over-restrictive bucket policy returned 403 for every export object.",
            metadata={
                "chunk_id": "chunk-0301",
                "doc_id": "doc-0301",
                "incident_id": "INC-2025-0301",
                "section": "Root Cause",
            },
        )
    ]


def test_existing_golden_file_still_loads_unchanged() -> None:
    questions = load_golden_questions(_GOLDEN_PATH)

    assert len(questions) == 89
    assert all(not question.is_adversarial for question in questions)
    assert all(question.forbidden_ids == [] and question.must_mention_ids == [] for question in questions)


def test_adversarial_file_loads_and_declares_its_traps() -> None:
    questions = load_golden_questions(_ADVERSARIAL_PATH)

    assert len(questions) == 13
    assert sum(question.expects_refusal for question in questions) == 2
    assert all(question.is_adversarial for question in questions)


def test_refusal_scored_correct_when_the_system_refuses() -> None:
    question = GoldenQuestion(
        question="What was the root cause of INC-2025-0999?",
        question_type="unanswerable",
        expects_refusal=True,
        forbidden_ids=["INC-2025-0301"],
    )

    result = adversarial_judge(
        question,
        "insufficient evidence in the retrieved context",
        [],
        _docs(),
    )

    assert result["refusal_correct"] == 1.0
    assert result["forbidden_id_leak"] == 0.0
    assert result["quality_score"] == 1.0


def test_refusal_that_leaks_a_nearby_incident_is_not_scored_clean() -> None:
    question = GoldenQuestion(
        question="What was the root cause of INC-2025-0999?",
        question_type="unanswerable",
        expects_refusal=True,
        forbidden_ids=["INC-2025-0301"],
    )

    result = adversarial_judge(
        question,
        "There is insufficient evidence in the retrieved context, but INC-2025-0301 was a bucket policy regression.",
        [],
        _docs(),
    )

    assert result["refusal_correct"] == 1.0
    assert result["forbidden_id_leak"] == 1.0
    assert result["quality_score"] < 1.0


def test_required_id_recall_counts_citations_as_naming_the_incident() -> None:
    question = GoldenQuestion(
        question="Which incident matches CDN 403s on exports?",
        question_type="semantic",
        must_mention_ids=["INC-2025-0301", "INC-2025-1002"],
    )
    citations = [
        Citation(doc_id="doc-0301", incident_id="INC-2025-0301", section="Root Cause", snippet="...")
    ]

    result = adversarial_judge(question, "A bucket policy regression caused it.", citations, _docs())

    assert result["required_id_recall"] == 0.5


def test_ungrounded_date_drags_the_score_down() -> None:
    question = GoldenQuestion(
        question="When did the export outage happen?",
        question_type="factual",
        must_mention_ids=["INC-2025-0301"],
    )

    clean = adversarial_judge(question, "INC-2025-0301 was a bucket policy regression.", [], _docs())
    dated = adversarial_judge(question, "INC-2025-0301 happened on 30 May.", [], _docs())

    assert clean["grounding_date_violations"] == 0
    assert dated["grounding_date_violations"] == 1
    assert dated["quality_score"] < clean["quality_score"]
