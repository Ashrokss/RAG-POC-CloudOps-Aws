"""
The routing tests use the real corpus (not a fixture) on purpose: the point of
the incident table is that it is complete, and a 3-row fixture cannot show
that "list every Lambda incident" reaches all ten of them when top-k=5
retrieval structurally cannot.
"""

from __future__ import annotations

from pathlib import Path

import pytest
from langchain_core.documents import Document

import rag.chain.rag_chain as rag_chain_module
from config.settings import get_settings
from rag.chain.rag_chain import retrieve_for_question
from rag.routing.dependency_graph import downstream_of, render_impact
from rag.routing.incident_table import filter_rows, incident_rows, render_rows
from rag.routing.router import classify, question_services
from rag.vectorstore.chroma_store import build_index

_AGGREGATE_QUESTIONS = [
    "List every incident involving AWS Lambda in chronological order with its date.",
    "Give me every dollar figure of financial or cost impact recorded anywhere in this corpus, and total them.",
    "Which incident had the longest gap between customer impact starting and detection?",
    "How many incidents involved capacity exhaustion?",
]

_RETRIEVAL_QUESTIONS = [
    "What was the root cause of INC-2025-0101?",
    "How did the on-call team mitigate the RDS IOPS throttling incident?",
    "Why was notification-dispatcher throttled during the launch spike?",
]

_BLAST_RADIUS_QUESTIONS = [
    "What services depend on RDS?",
    "What else breaks if IAM has an outage?",
    "What would be affected if ACM went down?",
    "What's the blast radius of an S3 failure?",
]


@pytest.mark.parametrize("question", _AGGREGATE_QUESTIONS)
def test_aggregate_questions_route_to_the_index(question: str) -> None:
    assert classify(question) == "aggregate"


@pytest.mark.parametrize("question", _RETRIEVAL_QUESTIONS)
def test_ordinary_questions_still_route_to_retrieval(question: str) -> None:
    assert classify(question) == "retrieval"


@pytest.mark.parametrize("question", _BLAST_RADIUS_QUESTIONS)
def test_blast_radius_questions_route_to_the_dependency_graph(question: str) -> None:
    assert classify(question) == "blast_radius"


def test_downstream_of_walks_the_okf_services_depends_on_graph() -> None:
    # Direct (glue depends_on rds) plus transitive (step-functions depends_on
    # glue) - the whole reason downstream_of exists rather than a one-hop
    # reverse lookup.
    assert set(downstream_of("rds")) == {"glue", "step-functions"}


def test_downstream_of_is_a_real_answer_not_zero_for_no_recorded_dependents() -> None:
    # Nothing in okf/services/*.md declares sqs in its own depends_on - a
    # legitimate "none recorded", not a bug, per canonical_service's same
    # "the curated layer is expected to lag" tolerance.
    assert downstream_of("sqs") == []
    assert downstream_of("not-a-real-service-id") == []


def test_render_impact_marks_no_dependents_as_recorded_not_absent() -> None:
    rendered = render_impact({"sqs": downstream_of("sqs")})
    assert "none recorded" in rendered

    rendered = render_impact({"rds": downstream_of("rds")})
    assert "glue" in rendered and "step-functions" in rendered


def test_blast_radius_route_downgrades_to_retrieval_with_no_named_service(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch, sample_chunks: list[Document]
) -> None:
    # "breaks if" matches _BLAST_RADIUS_RE, but "the coffee machine" resolves
    # to no okf/services/*.md id - retrieve_for_question must not ship an
    # empty DEPENDENCY IMPACT block, the same over-trigger tolerance
    # _AGGREGATE_RE already relies on.
    monkeypatch.setenv("CHROMA_PERSIST_DIR", str(tmp_path / "chroma"))
    monkeypatch.setenv("CHROMA_COLLECTION_NAME", "routing_blast_radius_downgrade_test")
    get_settings.cache_clear()
    monkeypatch.setattr(rag_chain_module, "_corpus_chunks", lambda: sample_chunks)
    build_index(sample_chunks, reset=True)

    question = "What else breaks if the coffee machine goes down?"
    assert classify(question) == "blast_radius"

    docs, index_block, route = retrieve_for_question(question, "hybrid", k=3)

    assert route == "retrieval"
    assert index_block == ""


def test_question_services_uses_the_okf_alias_map() -> None:
    assert question_services("every AWS Lambda incident") == ["lambda"]
    assert question_services("Redis or ElastiCache failures") == ["elasticache"]
    assert question_services("what broke in API Gateway") == ["api-gateway"]


def test_incident_table_covers_the_whole_corpus_and_is_date_sorted() -> None:
    rows = incident_rows()

    assert len(rows) == 25
    assert [row["date"] for row in rows] == sorted(row["date"] for row in rows)
    assert all(row["incident_id"] and row["doc_id"] for row in rows)


def test_filter_rows_selects_by_canonical_service_id() -> None:
    lambda_rows = filter_rows(incident_rows(), ["lambda"])

    # Ten documents list lambda once ingestion has normalised "Lambda"/"lambda"
    # to one id - the count the pre-T4 free-text metadata could not produce.
    assert len(lambda_rows) == 10
    assert all("lambda" in row["services"] for row in lambda_rows)


def test_render_rows_marks_missing_values_unknown_not_zero() -> None:
    rendered = render_rows(filter_rows(incident_rows(), ["bgp"]))

    # INC-2021-1004 records no cost; "0" there would read as a free outage.
    assert "unknown" in rendered
    assert "| 0 |" not in rendered.replace("| 0 | 0 |", "")


def test_aggregate_route_hands_over_every_matching_incident(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    monkeypatch.setenv("CHROMA_PERSIST_DIR", str(tmp_path / "chroma"))
    monkeypatch.setenv("CHROMA_COLLECTION_NAME", "routing_test")
    get_settings.cache_clear()
    build_index(list(rag_chain_module._corpus_chunks()), reset=True)

    question = "List every incident involving AWS Lambda in chronological order with its date."
    docs, index_block, route = retrieve_for_question(question, "hybrid", k=5)

    assert route == "aggregate"
    covered = {doc.metadata["incident_id"] for doc in docs}
    listed = {row["incident_id"] for row in filter_rows(incident_rows(), ["lambda"])}
    # Every incident the index lists also has chunk text in context, so each
    # enumerated row can be cited rather than asserted from metadata alone.
    assert listed <= covered
    assert all(incident_id in index_block for incident_id in listed)


def test_blast_radius_route_reports_the_dependency_impact_block(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    monkeypatch.setenv("CHROMA_PERSIST_DIR", str(tmp_path / "chroma"))
    monkeypatch.setenv("CHROMA_COLLECTION_NAME", "routing_blast_radius_test")
    get_settings.cache_clear()
    build_index(list(rag_chain_module._corpus_chunks()), reset=True)

    question = "What services depend on RDS, directly or transitively?"
    docs, index_block, route = retrieve_for_question(question, "hybrid", k=5)

    assert route == "blast_radius"
    assert "### DEPENDENCY IMPACT ###" in index_block
    assert "rds" in index_block
    assert "glue" in index_block and "step-functions" in index_block
    # No incident-index widening for this route - whatever the strategy
    # retrieved for "RDS" is left as-is, unlike aggregate_context.
    assert len(docs) <= 5


def test_retrieval_route_adds_no_index_block(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch, sample_chunks: list[Document]
) -> None:
    monkeypatch.setenv("CHROMA_PERSIST_DIR", str(tmp_path / "chroma"))
    monkeypatch.setenv("CHROMA_COLLECTION_NAME", "routing_retrieval_test")
    get_settings.cache_clear()
    monkeypatch.setattr(rag_chain_module, "_corpus_chunks", lambda: sample_chunks)
    build_index(sample_chunks, reset=True)

    docs, index_block, route = retrieve_for_question("What was the root cause of INC-2025-0101?", "hybrid", k=3)

    assert route == "retrieval"
    assert index_block == ""
    assert len(docs) <= 3


def test_index_answers_the_cost_total_question() -> None:
    # Q10 of the adversarial set. The model still has to add the figures up,
    # but every figure it needs - and no figure it does not - must be in front
    # of it, or the question is unanswerable however good the arithmetic is.
    rows = incident_rows()
    with_cost = {row["incident_id"]: row["cost_usd"] for row in rows if row["cost_usd"]}

    assert with_cost == {
        "INC-2025-0101": 61000,
        "INC-2025-0302": 13200,
        "INC-2025-0402": 380,
        "INC-2025-0601": 12400,
        "INC-2025-0702": 20700,
        "INC-2025-0801": 85000,
        "INC-2025-0902": 41000,
        "INC-2025-1001": 12500,
    }
    assert sum(with_cost.values()) == 246180


def test_index_answers_the_longest_detection_gap_question() -> None:
    # Q2 of the adversarial set - the one all four strategies failed live,
    # because the answer is a max over a column no retriever ever sees.
    rows = [row for row in incident_rows() if row["detection_gap_minutes"] is not None]

    worst = max(rows, key=lambda row: row["detection_gap_minutes"])

    assert worst["incident_id"] == "INC-2025-0302"
    assert worst["detection_gap_minutes"] == 387
