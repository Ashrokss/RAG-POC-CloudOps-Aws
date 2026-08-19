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
"""

from __future__ import annotations

import json
import time
from pathlib import Path

from rag.chain.rag_chain import generate, retrieve_only
from rag.models import GoldenQuestion
from rag.retrieval.factory import STRATEGIES

from eval.answer_quality import heuristic_judge, llm_judge
from eval.retrieval_metrics import mrr, precision_at_k, recall_at_k

_REPORTS_DIR = Path("reports")


def run_eval(
    golden_questions: list[GoldenQuestion],
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
            for golden_question in golden_questions:
                start = time.perf_counter()
                docs = retrieve_only(golden_question.question, strategy, k)
                retrieved_doc_ids = list(dict.fromkeys(doc.metadata["doc_id"] for doc in docs))
                answer, citations = generate(golden_question.question, docs)
                latency_ms = (time.perf_counter() - start) * 1000

                if judge == "heuristic":
                    judge_result = heuristic_judge(
                        answer,
                        golden_question.expected_answer_summary,
                        citations,
                        golden_question.relevant_doc_ids,
                    )
                elif judge == "llm":
                    judge_result = llm_judge(
                        golden_question.question, answer, golden_question.expected_answer_summary
                    )
                else:
                    raise ValueError(f"Unknown judge: {judge!r}. Valid judges: 'heuristic', 'llm'.")

                record = {
                    "run_label": run_label,
                    "strategy": strategy,
                    "question_type": golden_question.question_type,
                    "qid": golden_question.qid,
                    "question": golden_question.question,
                    "recall": recall_at_k(retrieved_doc_ids, golden_question.relevant_doc_ids),
                    "precision": precision_at_k(retrieved_doc_ids, golden_question.relevant_doc_ids),
                    "mrr": mrr(retrieved_doc_ids, golden_question.relevant_doc_ids),
                    "quality_score": judge_result["quality_score"],
                    "latency_ms": latency_ms,
                    "retrieved_doc_ids": retrieved_doc_ids,
                    "relevant_doc_ids": golden_question.relevant_doc_ids,
                    "answer": answer,
                    "citations": [citation.model_dump() for citation in citations],
                    "judge": judge,
                    "judge_details": {
                        field: value for field, value in judge_result.items() if field != "quality_score"
                    },
                }
                records.append(record)
                raw_file.write(json.dumps(record) + "\n")

    return records