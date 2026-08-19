"""
llm_judge is exercised only against MockChatModel (conftest.py forces mock
mode for the whole suite), so its assertions describe the mock's documented
placeholder behaviour - a hardcoded 0 for every required integer field, per
rag/llm/mock_chat_model.py's _placeholder_for_json_type - not a real Bedrock
judgment.
"""

from __future__ import annotations

from eval.answer_quality import heuristic_judge, llm_judge
from rag.models import Citation


def test_heuristic_judge_quality_score_in_range() -> None:
    result = heuristic_judge(
        generated_answer="The lambda outage was caused by exhausted reserved concurrency.",
        expected_answer_summary="Reserved concurrency exhaustion caused the lambda outage.",
        citations=[],
        relevant_doc_ids=[],
    )

    assert 0.0 <= result["quality_score"] <= 1.0


def test_heuristic_judge_detects_cited_relevant_doc() -> None:
    citations = [Citation(doc_id="doc-lambda", incident_id="INC-LAMBDA", section="Root Cause", snippet="...")]

    result = heuristic_judge(
        generated_answer="answer text",
        expected_answer_summary="summary text",
        citations=citations,
        relevant_doc_ids=["doc-lambda", "doc-rds"],
    )

    assert result["cited_relevant_doc"] is True


def test_heuristic_judge_detects_missing_relevant_citation() -> None:
    citations = [Citation(doc_id="doc-s3", incident_id="INC-S3", section="Root Cause", snippet="...")]

    result = heuristic_judge(
        generated_answer="answer text",
        expected_answer_summary="summary text",
        citations=citations,
        relevant_doc_ids=["doc-lambda", "doc-rds"],
    )

    assert result["cited_relevant_doc"] is False


def test_llm_judge_runs_against_mock_and_returns_scores_in_range() -> None:
    result = llm_judge(
        question="Why did the Lambda incident happen?",
        generated_answer="Reserved concurrency was exhausted.",
        expected_answer_summary="Reserved concurrency exhaustion caused the outage.",
    )

    assert 0.0 <= result["quality_score"] <= 1.0
    for field in ("faithfulness", "relevance", "completeness"):
        assert isinstance(result[field], int)
