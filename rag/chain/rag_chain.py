"""
retrieve_only and generate are kept separate, rather than folded into
answer_question, because retrieval-quality metrics (recall@k, MRR, ...) need
the raw retrieved-doc-id list independent of whatever the LLM does with it -
an eval harness scoring retrieval shouldn't have to run generation (or parse
citation text out of a model reply) just to get there.

retrieve_only rebuilds the corpus's chunk list from data/raw_rca_docs via
load_rca_documents/chunk_all - the same pipeline cli/ingest.py runs - rather
than reading chunks back out of Chroma's collection: chroma_store.py is
deliberately the only Chroma-aware module in this codebase, and chunk_id
(the one field a fresh chunk wouldn't share with its persisted counterpart,
since chunk_document() mints it from uuid4() on every call) isn't used by
keyword retrieval or by citation resolution, so re-chunking here costs
nothing correctness-wise for a corpus this small.

generate() calls get_chat_model() itself, and answer_question() calls it
again afterwards just to read off model_id - two lightweight client objects
instead of threading one through, so generate()'s signature stays exactly
(question, docs) for callers (like eval) that only want a citation-parsed
answer and don't care what model produced it.
"""

from __future__ import annotations

import re
import time
from pathlib import Path

from langchain_core.documents import Document
from langchain_core.output_parsers import StrOutputParser

from config.settings import get_settings
from rag.chain.prompt import RAG_PROMPT, SOURCE_HEADER_TEMPLATE
from rag.embeddings.factory import get_embeddings
from rag.ingestion.chunker import chunk_all
from rag.ingestion.loader import load_rca_documents
from rag.llm.factory import get_chat_model
from rag.models import Citation, RAGAnswer
from rag.retrieval.factory import get_retriever
from rag.vectorstore.chroma_store import get_vectorstore

_CORPUS_DIRS = [Path("data/raw_rca_docs/real"), Path("data/raw_rca_docs/synthetic")]

_CITATION_RE = re.compile(r"\[([^\]·]+)·([^\]]+)\]")
_SNIPPET_LENGTH = 150
_INSUFFICIENT_EVIDENCE_PHRASE = "insufficient evidence in the retrieved context"


def format_docs(docs: list[Document]) -> str:
    return "\n\n".join(
        SOURCE_HEADER_TEMPLATE.format(incident_id=doc.metadata["incident_id"], section=doc.metadata["section"])
        + "\n"
        + doc.page_content
        for doc in docs
    )


def _corpus_chunks() -> list[Document]:
    settings = get_settings()
    docs = load_rca_documents(_CORPUS_DIRS)
    return chunk_all(docs, settings.chunk_size, settings.chunk_overlap)


def retrieve_only(question: str, strategy: str, k: int) -> list[Document]:
    vectorstore = get_vectorstore(get_embeddings())
    chunks = _corpus_chunks()
    retriever = get_retriever(strategy, vectorstore, chunks, k)
    docs = retriever.invoke(question)

    # EnsembleRetriever's RRF fusion (hybrid/hybrid_rerank) can surface the
    # same chunk from both sub-retrievers as two separate list entries - a
    # live bake-off caught one duplicated at rank 9 and 12 in a single
    # answer's context, wasting prompt space without adding evidence.
    seen_chunk_ids: set[str] = set()
    deduped: list[Document] = []
    for doc in docs:
        chunk_id = doc.metadata["chunk_id"]
        if chunk_id in seen_chunk_ids:
            continue
        seen_chunk_ids.add(chunk_id)
        deduped.append(doc)
    return deduped


def _resolve_citations(answer: str, docs: list[Document]) -> list[Citation]:
    by_key = {(doc.metadata["incident_id"], doc.metadata["section"]): doc for doc in docs}
    citations: list[Citation] = []
    seen: set[tuple[str, str]] = set()

    for match in _CITATION_RE.finditer(answer):
        key = (match.group(1).strip(), match.group(2).strip())
        if key in seen or key not in by_key:
            continue
        seen.add(key)
        doc = by_key[key]
        citations.append(
            Citation(
                doc_id=doc.metadata["doc_id"],
                incident_id=key[0],
                section=key[1],
                snippet=doc.page_content[:_SNIPPET_LENGTH],
            )
        )
    return citations


def generate(question: str, docs: list[Document]) -> tuple[str, list[Citation]]:
    chain = RAG_PROMPT | get_chat_model() | StrOutputParser()
    context = format_docs(docs)
    answer = chain.invoke({"context": context, "question": question})
    citations = _resolve_citations(answer, docs)

    # A live bake-off found 5-7 of 13 answers per strategy named an incident
    # in prose without a resolvable citation tag - unauditable, since a
    # reviewer can't check a claim with no marker pointing at its source.
    # One retry with an explicit correction, rather than shipping that
    # answer: a refusal legitimately has zero citations, so it's excluded.
    if not citations and _INSUFFICIENT_EVIDENCE_PHRASE not in answer.lower():
        retry_question = (
            f"{question}\n\n"
            "Your previous answer did not cite any source chunk. Revise it: "
            "cite every factual claim using the [<incident id> · <section>] "
            "tag as instructed, or drop any claim you cannot cite."
        )
        answer = chain.invoke({"context": context, "question": retry_question})
        citations = _resolve_citations(answer, docs)

    return answer, citations


def answer_question(question: str, strategy: str = "hybrid", k: int | None = None) -> RAGAnswer:
    settings = get_settings()
    resolved_k = k if k is not None else settings.retrieval_top_k

    start = time.perf_counter()
    docs = retrieve_only(question, strategy, resolved_k)
    answer, citations = generate(question, docs)
    latency_ms = (time.perf_counter() - start) * 1000

    chat_model = get_chat_model()
    model_id = getattr(chat_model, "model", None) or chat_model._llm_type

    retrieved_doc_ids = list(dict.fromkeys(doc.metadata["doc_id"] for doc in docs))

    return RAGAnswer(
        question=question,
        strategy=strategy,
        answer=answer,
        citations=citations,
        retrieved_doc_ids=retrieved_doc_ids,
        latency_ms=latency_ms,
        model_id=model_id,
        mode="mock" if settings.mock_mode else "live",
    )
