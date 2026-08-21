"""
Tests for the v2 platform. The one that matters most is
test_full_loop_gap_to_promotion: it walks a question the corpus cannot answer
all the way to approved knowledge that answers it, which is the whole design
in one function.

Search and fetch are injected fixtures. Nothing here touches the network.
"""

from __future__ import annotations

from pathlib import Path

import pytest

from rca import gaps, research, review
from rca.answer import ask, format_incident_index, resolve_citations
from rca.ingest import _split_size, chunk_doc, ingest_dirs, markdown_adapter
from rca.models import Chunk
from rca.providers import EchoChatModel, HashEmbedder
from rca.retrieve import Retriever
from rca.router import classify, is_gap
from rca.store import Store
from rca.verify import verify

CORPUS = [Path("data/raw_rca_docs/real"), Path("data/raw_rca_docs/synthetic")]


@pytest.fixture
def store(tmp_path: Path) -> Store:
    s = Store(tmp_path / "test.db")
    ingest_dirs(s, CORPUS, embedder=HashEmbedder())
    return s


@pytest.fixture
def retriever(store: Store) -> Retriever:
    return Retriever(store, HashEmbedder())


# ---------- ingest ----------


def test_sliding_window_terminates_and_covers_the_text() -> None:
    # The first cut of this loop advanced by (len(window) - overlap) even on a
    # tail shorter than the overlap, so it emitted a near-duplicate chunk per
    # few characters: 25 docs became 5,754 chunks instead of ~230.
    text = "word " * 600
    parts = _split_size(text, 800, 120)

    assert 1 < len(parts) < 15
    assert all(len(p) <= 800 for p in parts)
    assert all(p in text for p in parts)


def test_ingest_is_idempotent(store: Store) -> None:
    before = store.counts()
    ingest_dirs(store, CORPUS, embedder=HashEmbedder())

    assert store.counts() == before


def test_chunk_ids_are_content_derived() -> None:
    doc = markdown_adapter(CORPUS[1] / "inc-2025-0101-rds-connection-pool-exhaustion.md")

    first = [c.chunk_id for c in chunk_doc(doc)]
    second = [c.chunk_id for c in chunk_doc(doc)]

    assert first == second and len(set(first)) == len(first)


def test_services_are_normalised_at_ingest(store: Store) -> None:
    # Frontmatter says "Lambda" in some docs and "lambda" in others.
    assert len(store.incidents(["lambda"])) == 10


def test_store_records_one_embedding_model(store: Store) -> None:
    assert store.embedding_models() == {"mock:hash-256"}


# ---------- retrieval and routing ----------


@pytest.mark.parametrize("k", [1, 3, 5, 10])
def test_hybrid_never_exceeds_k(retriever: Retriever, k: int) -> None:
    result = retriever.hybrid("lambda concurrency throttling", k)

    assert len(result.hits) <= k
    assert len({h.chunk.chunk_id for h in result.hits}) == len(result.hits)


def test_aggregate_questions_route_off_the_vector_index() -> None:
    assert classify("List every incident involving AWS Lambda") == "aggregate"
    assert classify("How many incidents involved IAM?") == "aggregate"
    assert classify("What was the root cause of INC-2025-0101?") == "retrieval"


def test_incident_index_is_complete_and_marks_unknowns(store: Store) -> None:
    rendered = format_incident_index(store.incidents())

    assert len(rendered.splitlines()) == 27  # header row + column names + 25 incidents
    # A missing cost must read as unknown, never as a free outage.
    assert "unknown" in rendered


def test_similar_incidents_is_symptom_keyed(retriever: Retriever) -> None:
    found = retriever.similar_incidents("EniLimitExceededException subnet IP exhaustion", 3)

    assert "INC-2025-0201" in found


def test_citations_resolve_only_against_retrieved_chunks() -> None:
    chunks = [
        Chunk(chunk_id="c1", doc_id="d1", section="Root Cause", ordinal=0, text="x",
              incident_id="INC-2025-0101")
    ]

    resolved = resolve_citations(
        "Real [INC-2025-0101 · Root Cause] and invented [INC-2025-9999 · Summary].", chunks
    )

    assert resolved == ["INC-2025-0101 · Root Cause"]


# ---------- gaps ----------


def test_unknown_incident_id_opens_a_gap(store: Store) -> None:
    # This one retrieves *well* - every incident id looks alike - so coverage
    # alone would never catch it.
    gap = gaps.detect(store, "What was the root cause of INC-2025-0999?", coverage=0.9)

    assert gap is not None and gap.reason == "unknown_entity"


def test_refusal_opens_a_gap(store: Store) -> None:
    gap = gaps.detect(
        store, "Summarise the etcd quorum-loss incident", coverage=0.9,
        answer="insufficient evidence in the retrieved context",
    )

    assert gap is not None and gap.reason == "refused"


def test_answerable_question_opens_no_gap(store: Store) -> None:
    assert gaps.detect(store, "What was the root cause of INC-2025-0101?", coverage=0.9) is None


def test_repeat_question_increments_one_gap(store: Store) -> None:
    for _ in range(3):
        gaps.detect(store, "What broke in INC-2025-0999?", coverage=0.1)

    open_gaps = store.gaps()
    assert len(open_gaps) == 1 and open_gaps[0].hit_count == 3


def test_is_gap_threshold() -> None:
    assert is_gap(0.10) and not is_gap(0.90)


# ---------- outbound sanitisation ----------


@pytest.mark.parametrize(
    "secret",
    [
        "418773529104",
        "arn:aws:iam::418773529104:role/billing",
        "subnet-0a1b2c3d4e5f67890",
        "orders-prod-pg.cluster-cabcxyz123.us-east-1.rds.amazonaws.com",
        "sre@example.com",
        "10.0.4.17",
        "INC-2025-0101",
    ],
)
def test_internal_identifiers_never_leave_in_a_search_query(secret: str) -> None:
    # A web search API is a third party. Incident text carries account ids,
    # bucket names and customer counts; only the sanitised symptom may go out.
    query = research.sanitise_query(f"Lambda EniLimitExceededException on {secret} during scale-out")

    assert secret not in query
    assert "EniLimitExceededException" in query


# ---------- verification ----------


def _fake_search(url: str = "https://docs.aws.amazon.com/lambda/vpc"):
    def search(query: str, limit: int = 3) -> list[dict]:
        return [{
            "url": url,
            "title": "Slot reservations",
            "text": "A reservation assigns a fixed number of slots to a workload, and queries queue when the reservation is fully consumed.",
        }]
    return search


def _fetch_ok(url: str) -> str:
    return (
        "Vendor docs. A reservation assigns a fixed number of slots to a workload, and queries "
        "queue when the reservation is fully consumed. Plan capacity accordingly."
    )


def _fetch_missing(url: str) -> str:
    return "This page says something else entirely about billing."


class _Refuser:
    """A model that refuses, which EchoChatModel cannot do - it quotes back
    whatever context it is handed, so it always appears to cite something. The
    refusal path is what a real model does with irrelevant context (verified
    live against gpt-4o-mini), and the loop hangs off it, so the loop test
    injects it rather than relying on a mock that cannot judge relevance."""

    model_id = "stub:refuser"

    def complete(self, system: str, user: str) -> str:
        return "insufficient evidence in the retrieved context"


class _Voter:
    """EchoChatModel cannot judge anything - it quotes context back - so a vote
    stub is injected rather than letting the echo mock's non-answer count as a
    refutation by accident. Verdicts under test should come from the rule being
    tested, not from a mock's incidental output."""

    model_id = "stub:voter"

    def __init__(self, supports: bool) -> None:
        self.supports = supports

    def complete(self, system: str, user: str) -> str:
        return "SUPPORTED" if self.supports else "REFUTED"


def test_verifier_approves_a_quote_that_is_actually_on_the_page(store: Store) -> None:
    gap = gaps.detect(store, "How does BigQuery slot reservation work?", coverage=0.1)
    card = research.research(store, gap, search=_fake_search())

    verdict = verify(store, card, _Voter(True), fetch=_fetch_ok, voters=1)

    assert verdict.approved
    assert verdict.quotes_verified == verdict.quotes_total == 1
    assert verdict.authority_score == 1.0


def test_verifier_rejects_a_quote_absent_from_its_source(store: Store) -> None:
    gap = gaps.detect(store, "How does BigQuery slot reservation work?", coverage=0.1)
    card = research.research(store, gap, search=_fake_search())

    verdict = verify(store, card, _Voter(True), fetch=_fetch_missing, voters=1)

    assert not verdict.approved
    assert store.get_candidate(card.candidate_id).status == "ai_rejected"


def test_verifier_defaults_to_reject_without_a_fetcher(store: Store) -> None:
    # No fetch means no quote could be checked. Unverifiable is not the same as
    # verified, and must not score as it.
    gap = gaps.detect(store, "How does BigQuery slot reservation work?", coverage=0.1)
    card = research.research(store, gap, search=_fake_search())

    assert not verify(store, card, _Voter(True), fetch=None, voters=1).approved


def test_community_source_alone_does_not_pass(store: Store) -> None:
    gap = gaps.detect(store, "How does BigQuery slot reservation work?", coverage=0.1)
    card = research.research(store, gap, search=_fake_search("https://randomblog.example/post"))

    verdict = verify(store, card, _Voter(True), fetch=_fetch_ok, voters=1)

    assert not verdict.approved
    assert "no vendor or official-postmortem source" in verdict.notes


def test_a_refuting_majority_blocks_a_card_with_perfect_sources(store: Store) -> None:
    # Everything mechanical passes here: quote verbatim, vendor source, no
    # conflicts. The voters still sink it, which is the point of having them.
    gap = gaps.detect(store, "How does BigQuery slot reservation work?", coverage=0.1)
    card = research.research(store, gap, search=_fake_search())

    assert not verify(store, card, _Voter(False), fetch=_fetch_ok, voters=3).approved


# ---------- the loop ----------


def test_full_loop_gap_to_promotion(store: Store, retriever: Retriever, tmp_path: Path) -> None:
    chat = _Refuser()
    # Deliberately a subject this corpus has never covered. "Why do VPC Lambdas
    # run out of ENIs" is *not* usable here - INC-2025-0201 answers it, so the
    # system correctly declines to open a gap, which is the behaviour under
    # test everywhere else in this file.
    question = "How does BigQuery slot reservation work?"

    # 1. asked, and unanswerable - the model says so, which is the signal
    answer = ask(store, retriever, chat, question)
    assert answer.route == "gap" and answer.gap_id
    assert store.get_gap(answer.gap_id).reason == "refused"

    # 2. researched into a quarantined candidate - invisible to retrieval
    gap = store.get_gap(answer.gap_id)
    card = research.research(store, gap, search=_fake_search())
    assert store.get_gap(gap.gap_id).status == "candidate"
    assert card.claim not in " ".join(c.text for c in store.all_chunks())

    # 3. verified adversarially
    verify(store, card, _Voter(True), fetch=_fetch_ok, voters=1)
    assert store.get_candidate(card.candidate_id).status == "ai_verified"

    # 4. promoted by a named human, and only then indexed
    path = review.approve(
        store, card.candidate_id, actor="sre@example.com",
        retriever=retriever, embedder=HashEmbedder(), cards_dir=tmp_path / "cards",
    )
    assert path.exists() and "approved_by: sre@example.com" in path.read_text()

    # 5. the knowledge is now retrievable, and the gap is closed
    assert any("fixed number of slots" in c.text for c in store.all_chunks())
    assert store.get_gap(gap.gap_id).status == "resolved"

    # ...and a model that can read it no longer produces a gap for the same
    # question, which is the loop actually closing rather than just running.
    reasked = ask(store, retriever, EchoChatModel(), question)
    assert reasked.route == "retrieval" and reasked.citations

    # 6. every step is attributable
    actions = [row["action"] for row in store.audit_trail()]
    assert "gap_opened" in actions and "candidate_promoted" in actions
    promotion = [r for r in store.audit_trail(card.candidate_id) if r["action"] == "candidate_promoted"]
    assert promotion and promotion[0]["actor"] == "sre@example.com"


def test_rejection_reopens_the_gap_and_records_why(store: Store) -> None:
    gap = gaps.detect(store, "How does BigQuery slot reservation work?", coverage=0.1)
    card = research.research(store, gap, search=_fake_search())
    verify(store, card, _Voter(True), fetch=_fetch_ok, voters=1)

    review.reject(store, card.candidate_id, actor="sre@example.com", reason="ambiguous source")

    # The question is still unanswered; closing it would teach the system to
    # stop asking.
    assert store.get_gap(gap.gap_id).status == "open"
    assert store.get_candidate(card.candidate_id).review_reason == "ambiguous source"


def test_rejection_requires_a_reason(store: Store) -> None:
    gap = gaps.detect(store, "How does BigQuery slot reservation work?", coverage=0.1)
    card = research.research(store, gap, search=_fake_search())

    with pytest.raises(ValueError, match="reason"):
        review.reject(store, card.candidate_id, actor="sre@example.com", reason="  ")


def test_unpromoted_candidates_are_never_retrievable(store: Store, retriever: Retriever) -> None:
    gap = gaps.detect(store, "How does BigQuery slot reservation work?", coverage=0.1)
    research.research(store, gap, search=_fake_search())

    hits = retriever.hybrid("reservation assigns a fixed number of slots", 10)

    assert all(hit.chunk.plane != "candidate" for hit in hits.hits)


def test_a_cited_answer_is_not_a_gap_however_low_the_score(store: Store) -> None:
    # After a knowledge card is promoted, the question it answers must stop
    # being reported as a gap. A resolved citation is direct evidence the
    # corpus held something usable; a similarity score is an inference about it.
    assert gaps.detect(store, "How does BigQuery slot reservation work?", coverage=0.05,
                       answer="answered [X · Claim]", citations=1) is None


def test_citations_do_not_excuse_an_unknown_incident(store: Store) -> None:
    gap = gaps.detect(store, "What caused INC-2025-0999?", coverage=0.9,
                      answer="It was a database failure [INC-2025-0101 · Root Cause]", citations=1)

    assert gap is not None and gap.reason == "unknown_entity"


def test_store_survives_use_from_another_thread(tmp_path: Path) -> None:
    # A web front end runs each request on a different thread from the one that
    # opened the store. sqlite3's default thread check rejects that outright,
    # which no single-threaded test could ever surface - the deployed page hit
    # it on first render.
    import threading

    s = Store(tmp_path / "threads.db")
    errors: list[Exception] = []

    def worker() -> None:
        try:
            s.audit("worker", "ping", "subject")
            s.counts()
        except Exception as exc:  # pragma: no cover - the assertion reports it
            errors.append(exc)

    thread = threading.Thread(target=worker)
    thread.start()
    thread.join()

    assert not errors, errors
    assert any(row["action"] == "ping" for row in s.audit_trail())


def test_a_question_naming_an_incident_retrieves_that_incident(retriever: Retriever) -> None:
    # Most chunks never repeat their own incident id, so without the identity
    # prefix in search_text this question retrieved a different incident
    # entirely - and the model answered it, with a citation, confidently wrong.
    top = retriever.keyword("What was the root cause of INC-2025-0101?", 3)

    assert top and top[0].chunk.incident_id == "INC-2025-0101"


def test_continuation_windows_do_not_start_mid_word() -> None:
    # "connection-count scaling" was retrieved and quoted as "n-count scaling".
    text = " ".join(f"token{i}" for i in range(400))
    parts = _split_size(text, 300, 60)

    assert all(p.split()[0].startswith("token") for p in parts)
    assert all(p.split()[-1].startswith("token") for p in parts)


def test_querying_with_the_wrong_embedder_fails_immediately(store: Store) -> None:
    # The store is built with the hash embedder; pretend a process wired to a
    # real Azure deployment points at it. Without this check the failure was a
    # numpy matmul error deep in search_vectors - and if the two models had
    # happened to share a dimension, no error at all.
    from rca.store import EmbeddingMismatchError

    class OtherEmbedder:
        model_id = "azure:text-embedding-3-small"

        def embed(self, texts: list[str]) -> list[list[float]]:
            return [[0.0] * 1536 for _ in texts]

    with pytest.raises(EmbeddingMismatchError, match="not comparable"):
        Retriever(store, OtherEmbedder())


def test_a_refusal_on_the_aggregate_route_still_opens_a_gap(store: Store, retriever: Retriever) -> None:
    # "How many connections does a Hyperplane ENI support" matches the
    # aggregate regex and is nothing of the sort. Suppressing gap detection for
    # the whole route meant the questions the corpus genuinely cannot answer
    # were the ones that never got recorded.
    class Refuser:
        model_id = "stub:refuser"

        def complete(self, system: str, user: str) -> str:
            return "insufficient evidence in the retrieved context"

    answer = ask(store, retriever, Refuser(), "How many connections does a Hyperplane ENI support?")

    assert answer.route == "gap" and answer.gap_id
    assert store.get_gap(answer.gap_id).reason == "refused"


def test_aggregate_route_ignores_the_coverage_floor(store: Store, retriever: Retriever) -> None:
    # The incident index answers these by construction, so a low chunk score
    # must not be read as "the corpus does not know".
    answer = ask(store, retriever, EchoChatModel(), "List every incident involving AWS Lambda")

    assert answer.route == "aggregate"
