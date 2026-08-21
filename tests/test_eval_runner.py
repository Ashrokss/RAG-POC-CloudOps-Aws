"""
Runs the harness over both kinds of question set in one invocation - the point
being that the two sets stay separated all the way through to the report, and
that an adversarial question is scored by the adversarial judge without the
caller having to ask for it.
"""

from __future__ import annotations

from pathlib import Path

import pytest
from langchain_core.documents import Document

import rag.chain.rag_chain as rag_chain_module
from config.settings import get_settings
from eval.report import build_csv_report, build_markdown_report
from eval.runner import run_eval
from rag.models import GoldenQuestion
from rag.vectorstore.chroma_store import build_index


@pytest.fixture
def _small_corpus(tmp_path: Path, monkeypatch: pytest.MonkeyPatch, sample_chunks: list[Document]) -> None:
    monkeypatch.setenv("CHROMA_PERSIST_DIR", str(tmp_path / "chroma"))
    monkeypatch.setenv("CHROMA_COLLECTION_NAME", "eval_runner_test")
    monkeypatch.chdir(tmp_path)
    get_settings.cache_clear()
    monkeypatch.setattr(rag_chain_module, "_corpus_chunks", lambda: sample_chunks)
    build_index(sample_chunks, reset=True)


def _question_sets() -> dict[str, list[GoldenQuestion]]:
    return {
        "golden": [
            GoldenQuestion(
                qid="g1",
                question="Why did Lambda start throttling?",
                question_type="factual",
                relevant_doc_ids=["doc-lambda"],
                expected_answer_summary="Reserved concurrency was exhausted during the spike.",
            )
        ],
        "adversarial": [
            GoldenQuestion(
                qid="a1",
                question="What was the root cause of INC-2025-0999?",
                question_type="unanswerable",
                expects_refusal=True,
                forbidden_ids=["INC-LAMBDA"],
            )
        ],
    }


def test_both_sets_run_in_one_invocation_and_stay_separate(_small_corpus: None) -> None:
    records = run_eval(_question_sets(), strategies=["hybrid"], k=2, run_label="test")

    assert {record["question_set"] for record in records} == {"golden", "adversarial"}
    by_set = {record["question_set"]: record for record in records}
    assert by_set["golden"]["judge"] == "heuristic"
    assert by_set["adversarial"]["judge"] == "adversarial"
    # The adversarial record carries the sub-scores; the golden one must not,
    # or a pooled average would silently invent refusal scores for questions
    # that were never asked to refuse.
    assert "refusal_correct" in by_set["adversarial"]
    assert "refusal_correct" not in by_set["golden"]


def test_reports_break_the_sets_out_separately(_small_corpus: None) -> None:
    records = run_eval(_question_sets(), strategies=["hybrid"], k=2, run_label="test")

    markdown = build_markdown_report(records)
    csv_text = build_csv_report(records)

    assert "## Question set: `golden`" in markdown
    assert "## Question set: `adversarial`" in markdown
    assert "refusal_correct" in markdown
    assert csv_text.splitlines()[0].startswith("question_set,strategy,question_type")
    assert len([line for line in csv_text.splitlines()[1:] if line]) == 2


def test_raw_jsonl_is_written_per_pair(_small_corpus: None, tmp_path: Path) -> None:
    run_eval(_question_sets(), strategies=["hybrid", "semantic"], k=2, run_label="jsonl")

    lines = (tmp_path / "reports" / "eval_raw_jsonl.jsonl").read_text(encoding="utf-8").splitlines()

    assert len(lines) == 4  # 2 strategies x 2 questions
