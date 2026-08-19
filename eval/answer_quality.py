"""
heuristic_judge is the default judge (config.settings.Settings.eval_judge_provider
defaults to "heuristic") because it has to produce a meaningful, non-constant
quality_score before any Bedrock credentials exist. MockChatModel's
_mock_answer already quotes real retrieved chunk text back verbatim, so
token overlap against expected_answer_summary tracks retrieval quality even
in mock mode - something a judge that asks an LLM to grade an LLM's answer
cannot do until that LLM is real.

llm_judge's schema fields carry no ge/le bound: MockChatModel's tool-call
placeholder for every required integer field is a hardcoded 0
(rag/llm/mock_chat_model.py's _placeholder_for_json_type), and a
bounds-checked 1-5 field would reject that placeholder with a ValidationError
instead of letting it pass through as the non-judgment it is. Clamping
happens once, in the quality_score normalization, instead of at the field
level.

RAGAS would give retrieval-grounded metrics (faithfulness, answer-relevancy)
without hand-rolled scoring prompts, but it's an optional stretch
enhancement, not a hard dependency of this harness - if it's ever wired in,
guard the import with try/except ImportError so environments without it
keep working.
"""

from __future__ import annotations

from pydantic import BaseModel, Field

from rag.llm.factory import get_chat_model
from rag.models import Citation

_JUDGE_PROMPT_TEMPLATE = """You are grading a RAG system's answer against a reference summary.

Question: {question}

Generated answer:
{generated_answer}

Reference answer summary:
{expected_answer_summary}

Score the generated answer on three dimensions, each from 1 (worst) to 5 (best):
- faithfulness: does the generated answer avoid contradicting or inventing facts not supported by the reference?
- relevance: does the generated answer address the question asked?
- completeness: does the generated answer cover what the reference summary covers?
"""


class _JudgeScores(BaseModel):
    faithfulness: int = Field(description="1-5, faithfulness of the answer to the reference")
    relevance: int = Field(description="1-5, relevance of the answer to the question")
    completeness: int = Field(description="1-5, completeness of the answer versus the reference")


def _tokenize(text: str) -> set[str]:
    return set(text.lower().split())


def heuristic_judge(
    generated_answer: str,
    expected_answer_summary: str,
    citations: list[Citation],
    relevant_doc_ids: list[str],
) -> dict:
    generated_tokens = _tokenize(generated_answer)
    expected_tokens = _tokenize(expected_answer_summary)
    union = generated_tokens | expected_tokens
    quality_score = len(generated_tokens & expected_tokens) / len(union) if union else 0.0

    cited_doc_ids = {citation.doc_id for citation in citations}
    cited_relevant_doc = any(doc_id in cited_doc_ids for doc_id in relevant_doc_ids)

    return {"quality_score": quality_score, "cited_relevant_doc": cited_relevant_doc}


def llm_judge(question: str, generated_answer: str, expected_answer_summary: str) -> dict:
    structured_model = get_chat_model().with_structured_output(_JudgeScores)
    prompt = _JUDGE_PROMPT_TEMPLATE.format(
        question=question,
        generated_answer=generated_answer,
        expected_answer_summary=expected_answer_summary,
    )
    scores: _JudgeScores = structured_model.invoke(prompt)

    average = (scores.faithfulness + scores.relevance + scores.completeness) / 3
    quality_score = max(0.0, min(1.0, (average - 1) / 4))

    return {
        "faithfulness": scores.faithfulness,
        "relevance": scores.relevance,
        "completeness": scores.completeness,
        "quality_score": quality_score,
    }