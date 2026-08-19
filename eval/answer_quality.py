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

adversarial_judge exists because neither judge above can fail an answer that
is fluent, on-vocabulary and wrong. It scores what the question actually
asked for - did the system refuse a question with no answer, did it name the
incidents that must be named, did it name one it must not, and does every
date and figure it stated beside an incident id appear in that incident's own
text. Those are pass/fail facts, not similarity scores.

RAGAS would give retrieval-grounded metrics (faithfulness, answer-relevancy)
without hand-rolled scoring prompts, but it's an optional stretch
enhancement, not a hard dependency of this harness - if it's ever wired in,
guard the import with try/except ImportError so environments without it
keep working.
"""

from __future__ import annotations

from langchain_core.documents import Document
from pydantic import BaseModel, Field

from rag.chain.grounding import INCIDENT_RE, check_grounding, count_by_kind
from rag.chain.rag_chain import INSUFFICIENT_EVIDENCE_PHRASE
from rag.llm.factory import get_chat_model
from rag.models import Citation, GoldenQuestion

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

def _mentioned_ids(answer: str, citations: list[Citation]) -> set[str]:
    """An incident counts as named if it appears in the answer text or in a
    resolved citation - a correct answer that cites INC-2025-0301 and describes
    it in prose without repeating the id has still named it."""
    cited = {citation.incident_id for citation in citations}
    return cited | {incident_id for incident_id in INCIDENT_RE.findall(answer)}


def adversarial_judge(
    golden_question: GoldenQuestion,
    generated_answer: str,
    citations: list[Citation],
    docs: list[Document],
) -> dict:
    mentioned = _mentioned_ids(generated_answer, citations)
    refused = INSUFFICIENT_EVIDENCE_PHRASE in generated_answer.lower()

    violations = check_grounding(generated_answer, docs)
    violation_counts = count_by_kind(violations)
    # Quoted claims only. A number an aggregate answer computed (a total) is
    # supposed to be absent from every source chunk, so counting it as
    # ungrounded would fail exactly the questions this set exists to ask.
    quoted_violations = violation_counts["date"] + violation_counts["unretrieved_incident"]

    result: dict = {
        "grounding_violations": len(violations),
        "grounding_date_violations": violation_counts["date"],
        "grounding_number_violations": violation_counts["number"],
        "grounding_unretrieved_incidents": violation_counts["unretrieved_incident"],
        "grounding_details": violations[:10],
    }

    components: list[float] = [1.0 if quoted_violations == 0 else 0.0]

    if golden_question.expects_refusal:
        result["refusal_correct"] = 1.0 if refused else 0.0
        components.append(result["refusal_correct"])

    if golden_question.must_mention_ids:
        hits = sum(1 for incident_id in golden_question.must_mention_ids if incident_id in mentioned)
        result["required_id_recall"] = hits / len(golden_question.must_mention_ids)
        components.append(result["required_id_recall"])

    if golden_question.forbidden_ids:
        leaked = [incident_id for incident_id in golden_question.forbidden_ids if incident_id in mentioned]
        # A refusal that also volunteers a nearby incident's root cause is the
        # failure this catches: refusal_correct alone would score it 1.0.
        result["forbidden_id_leak"] = 1.0 if leaked else 0.0
        result["forbidden_ids_leaked"] = leaked
        components.append(0.0 if leaked else 1.0)

    result["quality_score"] = sum(components) / len(components)
    return result
