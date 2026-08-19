"""
_corpus_chunks is monkeypatched to a small fixed corpus rather than letting
retrieve_only read the real data/raw_rca_docs tree, so this test stays
correct regardless of how many incidents get added there later and never
depends on a chroma_db directory a previous ingest run may or may not have
already populated on disk.
"""

from __future__ import annotations

from datetime import datetime, timezone
from pathlib import Path
from typing import Any, Optional

import pytest
from langchain_core.callbacks import CallbackManagerForLLMRun
from langchain_core.documents import Document
from langchain_core.language_models.chat_models import BaseChatModel
from langchain_core.messages import AIMessage, BaseMessage
from langchain_core.outputs import ChatGeneration, ChatResult
from pydantic import PrivateAttr

import rag.chain.rag_chain as rag_chain_module
from config.settings import get_settings
from rag.chain.rag_chain import answer_question, generate
from rag.models import RAGAnswer, RCADocumentMeta
from rag.vectorstore.chroma_store import build_index


class _ScriptedChatModel(BaseChatModel):
    """Returns responses[0], then responses[1], ... on successive calls,
    repeating the last one past the end - a fixed script rather than
    MockChatModel's chunk-echoing, so generate()'s retry logic (does it
    skip the citation retry for a DEPENDENCY IMPACT answer, does it retry
    once more on a missing-service completeness violation) is exercised
    deterministically rather than relying on a live spot-check every time."""

    _responses: list[str] = PrivateAttr()
    _call_count: int = PrivateAttr(default=0)

    def __init__(self, responses: list[str], **kwargs: Any) -> None:
        super().__init__(**kwargs)
        self._responses = responses
        self._call_count = 0

    @property
    def _llm_type(self) -> str:
        return "scripted-chat"

    @property
    def call_count(self) -> int:
        return self._call_count

    def _generate(
        self,
        messages: list[BaseMessage],
        stop: Optional[list[str]] = None,
        run_manager: Optional[CallbackManagerForLLMRun] = None,
        **kwargs: Any,
    ) -> ChatResult:
        index = min(self._call_count, len(self._responses) - 1)
        self._call_count += 1
        return ChatResult(generations=[ChatGeneration(message=AIMessage(content=self._responses[index]))])


def test_answer_question_returns_well_formed_answer(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch, sample_chunks: list[Document]
) -> None:
    monkeypatch.setenv("CHROMA_PERSIST_DIR", str(tmp_path / "chroma"))
    monkeypatch.setenv("CHROMA_COLLECTION_NAME", "rag_chain_test")
    get_settings.cache_clear()
    monkeypatch.setattr(rag_chain_module, "_corpus_chunks", lambda: sample_chunks)
    build_index(sample_chunks, reset=True)

    answer = answer_question("Why did Lambda start throttling?", strategy="hybrid")

    assert isinstance(answer, RAGAnswer)
    assert answer.mode == "mock"
    assert answer.answer != ""
    assert len(answer.retrieved_doc_ids) > 0
    assert answer.latency_ms >= 0


def test_corpus_is_loaded_once_across_repeated_queries(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    # Reading and re-chunking every RCA file per query is the cost this cache
    # exists to remove; an eval run pays it once per (question x strategy)
    # otherwise.
    monkeypatch.setenv("CHROMA_PERSIST_DIR", str(tmp_path / "chroma"))
    monkeypatch.setenv("CHROMA_COLLECTION_NAME", "corpus_cache_test")
    get_settings.cache_clear()

    meta = RCADocumentMeta(
        incident_id="INC-CACHE-0001",
        title="Cached Incident",
        date=datetime(2025, 1, 1, tzinfo=timezone.utc),
        severity="high",
        services=["lambda"],
        region="us-east-1",
        account_id="123456789012",
        status="resolved",
        tags=["cache"],
        source="synthetic",
    )
    body = "## Root Cause\n\nReserved concurrency was exhausted during the spike.\n"

    load_calls: list[object] = []

    def _counting_loader(root_dirs: object) -> list[tuple[RCADocumentMeta, str]]:
        load_calls.append(root_dirs)
        return [(meta, body)]

    monkeypatch.setattr(rag_chain_module, "load_rca_documents", _counting_loader)
    build_index(rag_chain_module._corpus_chunks(), reset=True)

    for _ in range(10):
        rag_chain_module.retrieve_only("Why did Lambda throttle?", "hybrid", k=3)

    assert len(load_calls) == 1


_ACM_IMPACT_BLOCK = (
    "### DEPENDENCY IMPACT ###\n"
    "acm -> depended on by (directly or transitively): alb, cloudfront, ecs, route-53"
)


def test_generate_skips_the_citation_retry_for_a_dependency_impact_answer(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    # A DEPENDENCY IMPACT answer is instructed to carry zero citations unless
    # an excerpt backs one. The ordinary citation retry ("cite every claim...
    # or drop any claim you cannot cite") must not fire here - a live
    # spot-check showed that exact push is what made the model drop services
    # it had no excerpt for.
    stub = _ScriptedChatModel(responses=["ALB and CloudFront depend on ACM."])
    monkeypatch.setattr(rag_chain_module, "get_chat_model", lambda: stub)

    small_block = (
        "### DEPENDENCY IMPACT ###\nacm -> depended on by (directly or transitively): alb, cloudfront"
    )
    answer, citations = generate("What depends on ACM?", docs=[], index_block=small_block)

    assert citations == []
    assert stub.call_count == 1


def test_generate_retries_once_when_a_dependency_answer_omits_a_service(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    stub = _ScriptedChatModel(
        responses=[
            "ALB and CloudFront depend on ACM.",  # omits ecs, route-53
            "ALB, CloudFront, ECS, and Route 53 all depend on ACM.",  # complete
        ]
    )
    monkeypatch.setattr(rag_chain_module, "get_chat_model", lambda: stub)

    answer, _ = generate(
        "What would be affected downstream if ACM had an outage?", docs=[], index_block=_ACM_IMPACT_BLOCK
    )

    assert stub.call_count == 2
    assert "ECS" in answer and "Route 53" in answer


def test_generate_does_not_retry_an_already_complete_dependency_answer(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    stub = _ScriptedChatModel(responses=["ALB, CloudFront, ECS, and Route 53 would all be affected."])
    monkeypatch.setattr(rag_chain_module, "get_chat_model", lambda: stub)

    generate(
        "What would be affected downstream if ACM had an outage?", docs=[], index_block=_ACM_IMPACT_BLOCK
    )

    assert stub.call_count == 1


def _grounded_docs() -> list[Document]:
    return [
        Document(
            page_content=(
                "On 2025-10-02 the module bump broke the trust policy. "
                "The reconciler was delayed 84 minutes."
            ),
            metadata={
                "chunk_id": "chunk-1002",
                "doc_id": "doc-1002",
                "incident_id": "INC-2025-1002",
                "section": "Summary",
            },
        )
    ]


def test_generate_retries_when_a_stated_date_is_not_grounded(monkeypatch: pytest.MonkeyPatch) -> None:
    # Mirrors the actual live bake-off failure check_grounding was built to
    # catch: a right incident, wrong date, that a citation tag alone cannot
    # reveal since the tag itself is correct.
    stub = _ScriptedChatModel(
        responses=[
            "INC-2025-1002 occurred on 30 May and delayed the reconciler 84 minutes [INC-2025-1002 · Summary].",
            "INC-2025-1002 occurred on 2 October and delayed the reconciler 84 minutes [INC-2025-1002 · Summary].",
        ]
    )
    monkeypatch.setattr(rag_chain_module, "get_chat_model", lambda: stub)

    answer, _ = generate("When did INC-2025-1002 happen?", docs=_grounded_docs())

    assert stub.call_count == 2
    assert "October" in answer


def test_generate_does_not_retry_for_a_legitimate_computed_total(monkeypatch: pytest.MonkeyPatch) -> None:
    # A "number" violation alone must never trigger a retry: an aggregate
    # total is supposed to be a figure that appears nowhere in the source -
    # that's the point of asking for one - so retrying it would fight the
    # question rather than fix an error.
    stub = _ScriptedChatModel(
        responses=["INC-2025-1002's cascading cost came to $41,400 across two teams [INC-2025-1002 · Summary]."]
    )
    monkeypatch.setattr(rag_chain_module, "get_chat_model", lambda: stub)

    generate("What was the total cost of INC-2025-1002?", docs=_grounded_docs())

    assert stub.call_count == 1


def test_generate_does_not_retry_an_already_grounded_answer(monkeypatch: pytest.MonkeyPatch) -> None:
    stub = _ScriptedChatModel(
        responses=["INC-2025-1002 occurred on 2 October and delayed the reconciler 84 minutes [INC-2025-1002 · Summary]."]
    )
    monkeypatch.setattr(rag_chain_module, "get_chat_model", lambda: stub)

    generate("When did INC-2025-1002 happen?", docs=_grounded_docs())

    assert stub.call_count == 1
