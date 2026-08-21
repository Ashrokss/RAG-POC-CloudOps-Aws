"""
Each (strategy, question) pair's raw record is appended to
reports/eval_raw_<run_label>.jsonl as it's produced, not batched into one
write at the end of run_eval: a live-Bedrock eval run over four strategies
and a real golden set is the slowest, most failure-prone thing this codebase
does (network calls, rate limits, a stray malformed prompt), and a JSONL
file that already has every completed pair on disk survives a crash on pair
N+1 without losing pairs 1..N.

run_label is a required, caller-supplied string (default "latest") rather
than a timestamp minted here, because this environment has no reliable
wall-clock/time-of-day source to stamp filenames with - the caller (a human
running cli/eval.py, or a test) is in a better position to pick a stable,
meaningful label than a function that can't safely ask the OS what time it
is. It is threaded straight through into the raw-JSONL and (via
eval/report.py's write_reports) the comparison-report filenames, with no
generation or defaulting logic beyond the plain default value.

Question sets are a mapping of label -> questions, not one flat list, because
the golden set and the adversarial set are scored by different judges and
must never be averaged together: the golden set's 88 questions are answerable
from one retrievable chunk (86) or the okf/ dependency graph via the
blast_radius route (2) - never designed to be unanswerable - so pooling them
with 13 questions designed to be unanswerable, corpus-wide or arithmetic
would let a strong score on the easy set hide a total failure on the hard
one. Every record carries its set label and the reports break out one table
per set.

Retrieval goes through rag_chain.retrieve_for_question rather than
retrieve_only, so a scored run takes the same route (retrieval or aggregate)
a user's question would - scoring a path the product doesn't use is how an
eval harness ends up green while the app is wrong.
"""

from __future__ import annotations

import json
import time
from pathlib import Path

from rag.chain.rag_chain import generate, retrieve_for_question
from rag.models import GoldenQuestion
from rag.retrieval.factory import STRATEGIES
from rag.routing.incident_table import incident_rows

from eval.answer_quality import adversarial_judge, heuristic_judge, llm_judge
from eval.retrieval_metrics import mrr, precision_at_k, recall_at_k
from rag.routing.dependency_graph import check_dependency_completeness

_REPORTS_DIR = Path("reports")


def _resolve_relevant_doc_ids(golden_question: GoldenQuestion) -> list[str]:
    """Adversarial questions are authored with incident ids (what a human
    knows) and no doc ids (UUIDs nobody should hand-copy); retrieval metrics
    need doc ids. Resolve one to the other against the incident table."""
    if golden_question.relevant_doc_ids or not golden_question.must_mention_ids:
        return golden_question.relevant_doc_ids

    by_incident = {row["incident_id"]: row["doc_id"] for row in incident_rows()}
    return [
        by_incident[incident_id]
        for incident_id in golden_question.must_mention_ids
        if incident_id in by_incident
    ]


def run_eval(
    question_sets: dict[str, list[GoldenQuestion]],
    strategies: list[str] | None = None,
    k: int = 5,
    judge: str = "heuristic",
    run_label: str = "latest",
) -> list[dict]:
    resolved_strategies = list(strategies) if strategies is not None else list(STRATEGIES)

    _REPORTS_DIR.mkdir(parents=True, exist_ok=True)
    raw_path = _REPORTS_DIR / f"eval_raw_{run_label}.jsonl"

    records: list[dict] = []
    with raw_path.open("w", encoding="utf-8") as raw_file:
        for strategy in resolved_strategies:
            for set_label, golden_questions in question_sets.items():
                for golden_question in golden_questions:
                    records.append(
                        _score_one(
                            golden_question, set_label, strategy, k, judge, run_label, raw_file
                        )
                    )

    return records


def _score_one(
    golden_question: GoldenQuestion,
    set_label: str,
    strategy: str,
    k: int,
    judge: str,
    run_label: str,
    raw_file,
) -> dict:
    start = time.perf_counter()
    docs, index_block, route = retrieve_for_question(golden_question.question, strategy, k)
    retrieved_doc_ids = list(dict.fromkeys(doc.metadata["doc_id"] for doc in docs))
    answer, citations = generate(golden_question.question, docs, index_block)
    latency_ms = (time.perf_counter() - start) * 1000

    relevant_doc_ids = _resolve_relevant_doc_ids(golden_question)

    if golden_question.is_adversarial:
        judge_name = "adversarial"
        judge_result = adversarial_judge(golden_question, answer, citations, docs)
    elif judge == "heuristic":
        judge_name = judge
        judge_result = heuristic_judge(
            answer, golden_question.expected_answer_summary, citations, relevant_doc_ids
        )
    elif judge == "llm":
        judge_name = judge
        judge_result = llm_judge(
            golden_question.question, answer, golden_question.expected_answer_summary
        )
    else:
        raise ValueError(f"Unknown judge: {judge!r}. Valid judges: 'heuristic', 'llm'.")

    record = {
        "run_label": run_label,
        "question_set": set_label,
        "strategy": strategy,
        "route": route,
        "question_type": golden_question.question_type,
        "qid": golden_question.qid,
        "question": golden_question.question,
        "recall": recall_at_k(retrieved_doc_ids, relevant_doc_ids),
        "precision": precision_at_k(retrieved_doc_ids, relevant_doc_ids),
        "mrr": mrr(retrieved_doc_ids, relevant_doc_ids),
        "quality_score": judge_result["quality_score"],
        "latency_ms": latency_ms,
        "retrieved_doc_ids": retrieved_doc_ids,
        "relevant_doc_ids": relevant_doc_ids,
        "answer": answer,
        "citations": [citation.model_dump() for citation in citations],
        "judge": judge_name,
        "judge_details": {
            field: value for field, value in judge_result.items() if field != "quality_score"
        },
    }
    # Adversarial sub-scores are promoted to top-level numeric fields so
    # aggregate_metrics averages them into the report instead of leaving them
    # buried in judge_details where nothing reads them.
    for field in (
        "refusal_correct",
        "required_id_recall",
        "forbidden_id_leak",
        "outside_knowledge_lines",
        "grounding_violations",
        "grounding_date_violations",
        "grounding_number_violations",
        "grounding_unretrieved_incidents",
    ):
        if field in judge_result:
            record[field] = judge_result[field]

    # Independent of the judge/adversarial branch above: this checks whether
    # the answer's prose named every downstream service the blast_radius
    # route handed the model, not whether the answer is otherwise good - a
    # golden-set blast_radius question is not adversarial, so it would
    # otherwise never get checked for exactly the completeness gap a live
    # spot-check found (ACM's transitive dependents silently dropped).
    if route == "blast_radius":
        dependency_violations = check_dependency_completeness(answer, index_block)
        record["dependency_completeness_violations"] = len(dependency_violations)
        record["dependency_completeness_details"] = dependency_violations

    raw_file.write(json.dumps(record) + "\n")
    return record
