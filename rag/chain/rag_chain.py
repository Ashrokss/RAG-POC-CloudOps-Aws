"""
retrieve_only and generate are kept separate, rather than folded into
answer_question, because retrieval-quality metrics (recall@k, MRR, ...) need
the raw retrieved-doc-id list independent of whatever the LLM does with it -
an eval harness scoring retrieval shouldn't have to run generation (or parse
citation text out of a model reply) just to get there.

retrieve_only rebuilds the corpus's chunk list from data/raw_rca_docs via
load_rca_documents/chunk_all - the same pipeline cli/ingest.py runs - rather
than reading chunks back out of Chroma's collection: chroma_store.py is
deliberately the only Chroma-aware module in this codebase, and chunk_id is
now derived deterministically from (doc_id, section, ordinal), so an
in-memory chunk and its persisted counterpart in Chroma are the same chunk
under the same id.

That rebuild - every markdown file read, frontmatter-parsed and re-split, plus
a BM25 index built over the result - used to run on every single query, for
every strategy, including semantic, which never touches the chunk list. Both
it and the built retriever are cached now (the retriever per (strategy, k),
since that pair is all it depends on). Anything that changes what is on disk
or in the collection must call reset_corpus_cache(); the test suite does this
between tests, and a re-ingest is a separate process that starts cold.

generate() calls get_chat_model() itself, and answer_question() calls it
again afterwards just to read off model_id - two lightweight client objects
instead of threading one through, so generate()'s signature stays exactly
(question, docs) for callers (like eval) that only want a citation-parsed
answer and don't care what model produced it.
"""

from __future__ import annotations

import re
import time
from functools import lru_cache

from langchain_core.documents import Document
from langchain_core.output_parsers import StrOutputParser
from langchain_core.retrievers import BaseRetriever

from config.settings import get_settings
from rag.chain.grounding import check_grounding, split_outside_knowledge
from rag.chain.prompt import OUTSIDE_KNOWLEDGE_MARKER, RAG_PROMPT, SOURCE_HEADER_TEMPLATE
from rag.embeddings.factory import get_embeddings
from rag.ingestion.chunker import chunk_all
from rag.ingestion.loader import CORPUS_DIRS, load_rca_documents
from rag.llm.factory import get_chat_model
from rag.models import Citation, RAGAnswer
from rag.retrieval.factory import get_retriever
from rag.routing.dependency_graph import (
    check_dependency_completeness,
    downstream_of,
    render_impact,
    reset_dependency_graph,
)
from rag.routing.incident_table import filter_rows, incident_rows, render_rows, reset_incident_table
from rag.routing.router import classify, question_services
from rag.vectorstore.chroma_store import get_vectorstore

_CITATION_RE = re.compile(r"\[([^\]·]+)·([^\]]+)\]")
_SNIPPET_LENGTH = 150
# Two chunks per incident, preferred sections first: enough for the model to
# cite real text for each row it enumerates, without a 25-incident index
# dragging the entire corpus into the prompt behind it.
_AGGREGATE_CHUNKS_PER_INCIDENT = 2
_AGGREGATE_CHUNK_BUDGET = 30
_PREFERRED_SECTIONS = ("Summary", "Impact", "Root Cause", "Detection")
INSUFFICIENT_EVIDENCE_PHRASE = "insufficient evidence in the retrieved context"


def format_docs(docs: list[Document]) -> str:
    return "\n\n".join(
        SOURCE_HEADER_TEMPLATE.format(incident_id=doc.metadata["incident_id"], section=doc.metadata["section"])
        + "\n"
        + doc.page_content
        for doc in docs
    )


@lru_cache(maxsize=1)
def _corpus_chunks() -> list[Document]:
    # Callers must treat the returned list as read-only - it is the one shared
    # copy every retriever in this process is built from.
    settings = get_settings()
    docs = load_rca_documents(list(CORPUS_DIRS))
    return chunk_all(docs, settings.chunk_size, settings.chunk_overlap)


@lru_cache(maxsize=16)
def _cached_retriever(strategy: str, k: int) -> BaseRetriever:
    # (strategy, k) is the retriever's whole identity: the vector store handle
    # and the chunk list behind it are fixed for the process's lifetime, and
    # rebuilding BM25 from 233 chunks per call was pure waste - an 88-question
    # eval across 4 strategies paid for it 352 times.
    #
    # keyword is pure BM25 over the chunk list and never touches Chroma, so it
    # must not open the collection: doing so made an embedding-model mismatch
    # fail the one strategy that has no embeddings to mismatch.
    vectorstore = None if strategy == "keyword" else get_vectorstore(get_embeddings())
    return get_retriever(strategy, vectorstore, _corpus_chunks(), k)


def reset_corpus_cache() -> None:
    """Drop both caches. Needed after the corpus on disk or the collection
    changes underneath a live process (and between tests).

    getattr rather than a direct .cache_clear() call: tests monkeypatch
    _corpus_chunks with a plain function, which has no cache to clear, and
    teardown must not care which of the two it is looking at."""
    for cached in (_corpus_chunks, _cached_retriever):
        clear = getattr(cached, "cache_clear", None)
        if clear is not None:
            clear()
    reset_incident_table()
    reset_dependency_graph()


def retrieve_only(question: str, strategy: str, k: int) -> list[Document]:
    docs = _cached_retriever(strategy, k).invoke(question)

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

    # k is a contract across all four strategies, not a hint. EnsembleRetriever
    # (hybrid) fuses two k-wide rankings by RRF and truncates nothing, so it
    # returned up to 2k documents where semantic/keyword/hybrid_rerank returned
    # exactly k - a live bake-off saw 9-10 chunks at k=5 and 18 at k=10. That
    # made every cross-strategy comparison apples-to-oranges twice over: hybrid
    # got double the context to answer from, and eval/retrieval_metrics.py's
    # precision_at_k divides by len(retrieved), so hybrid was structurally
    # penalised on precision no matter how good its ranking was.
    return deduped[:k]


def _supporting_chunks(rows: tuple[dict, ...], already_have: list[Document]) -> list[Document]:
    """Chunk text for the incidents the index lists, so an enumerated answer can
    cite each row instead of asserting it from metadata alone."""
    seen = {doc.metadata["chunk_id"] for doc in already_have}
    by_incident: dict[str, list[Document]] = {}
    for chunk in _corpus_chunks():
        by_incident.setdefault(chunk.metadata["incident_id"], []).append(chunk)

    supporting: list[Document] = []
    for row in rows:
        candidates = by_incident.get(row["incident_id"], [])
        ranked = sorted(
            candidates,
            key=lambda doc: _PREFERRED_SECTIONS.index(doc.metadata["section"])
            if doc.metadata["section"] in _PREFERRED_SECTIONS
            else len(_PREFERRED_SECTIONS),
        )
        for chunk in ranked[:_AGGREGATE_CHUNKS_PER_INCIDENT]:
            if chunk.metadata["chunk_id"] in seen or len(supporting) >= _AGGREGATE_CHUNK_BUDGET:
                continue
            seen.add(chunk.metadata["chunk_id"])
            supporting.append(chunk)
    return supporting


def aggregate_context(question: str, docs: list[Document]) -> tuple[str, list[Document]]:
    """The incident index for this question, plus the retrieved chunks widened
    to cover every incident the index lists."""
    rows = filter_rows(incident_rows(), question_services(question))
    index_block = "### INCIDENT INDEX ###\n" + render_rows(rows)
    return index_block, docs + _supporting_chunks(rows, docs)


def blast_radius_context(question: str) -> str:
    """The '### DEPENDENCY IMPACT ###' block: which services would be
    affected, directly or transitively, if each service named in the
    question failed - from okf/services/*.md's depends_on graph, not from
    any incident. Unlike aggregate_context, this never widens docs: the
    graph is a structural fact about the architecture, not a claim that
    needs incident chunk text to back it - whatever the chosen strategy
    already retrieved for the named service(s) is left as-is."""
    origins = question_services(question)
    if not origins:
        return ""
    impact = {origin: downstream_of(origin) for origin in origins}
    return "### DEPENDENCY IMPACT ###\n" + render_impact(impact)


def retrieve_for_question(question: str, strategy: str, k: int) -> tuple[list[Document], str, str]:
    """(docs, index_block, route) - the whole pre-generation half of answering.
    The eval harness calls this rather than re-deriving the route itself, so a
    scored run and a user-facing answer cannot diverge on which path ran."""
    route = classify(question)
    docs = retrieve_only(question, strategy, k)
    index_block = ""
    if route == "aggregate":
        index_block, docs = aggregate_context(question, docs)
    elif route == "blast_radius":
        index_block = blast_radius_context(question)
        if not index_block:
            # No named service to compute a dependency graph against - the
            # same graceful downgrade _AGGREGATE_RE's over-triggering already
            # relies on, rather than shipping an empty DEPENDENCY IMPACT block.
            route = "retrieval"
    return docs, index_block, route


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


def _find_corrections(
    answer: str,
    citations: list[Citation],
    docs: list[Document],
    index_block: str,
    is_dependency_answer: bool,
) -> list[str]:
    """Every issue worth retrying for, gathered up front rather than retried
    one at a time - a second retry re-fixing what the first retry re-broke
    is worse than one pass telling the model everything at once."""
    corrections: list[str] = []

    # A live bake-off found 5-7 of 13 answers per strategy named an incident
    # in prose without a resolvable citation tag - unauditable, since a
    # reviewer can't check a claim with no marker pointing at its source. A
    # refusal legitimately has zero citations, so it's excluded, and so is a
    # DEPENDENCY IMPACT answer: that block is instructed to state structural
    # facts with no citation tag unless an excerpt genuinely backs one, so
    # zero citations there is the designed outcome, not a defect - telling
    # the model to "cite every claim... or drop any claim you cannot cite"
    # would push it toward dropping exactly the facts this check exists to
    # keep.
    # ...and so is an answer whose substance sits below OUTSIDE_KNOWLEDGE_MARKER:
    # it is openly labelled as not coming from this corpus, so demanding
    # citations for it would only pressure the model into citing chunks it
    # did not use.
    if (
        not is_dependency_answer
        and not citations
        and INSUFFICIENT_EVIDENCE_PHRASE not in answer.lower()
        and OUTSIDE_KNOWLEDGE_MARKER not in answer
    ):
        corrections.append(
            "You did not cite any source chunk. Cite every factual claim using the "
            "[<incident id> · <section>] tag as instructed, or drop any claim you cannot cite."
        )

    # The DEPENDENCY IMPACT block's own counterpart to the citation check
    # above: the model can be handed every downstream service and still only
    # narrate the ones also named in a retrieved excerpt, silently dropping
    # the rest.
    if is_dependency_answer:
        missing = check_dependency_completeness(answer, index_block)
        if missing:
            missing_ids = ", ".join(sorted({violation["missing_service"] for violation in missing}))
            corrections.append(
                f"You omitted the following service(s) that the DEPENDENCY IMPACT block "
                f"lists as affected: {missing_ids}. Name every service the block lists, "
                f"including these - no incident citation is required for them."
            )

    # Only date and unretrieved-incident violations, never number: a
    # legitimate aggregate answer computes totals that appear nowhere in the
    # source by construction (that is the whole point of asking for one), so
    # retrying those would fight the question rather than fix an error. This
    # cannot catch the wrong-but-real-figure case (a genuine data-staleness
    # figure quoted where a detection-gap figure was asked for) - both
    # numbers are real, so nothing here is unsupported; see rag/chain/
    # grounding.py's docstring.
    grounding_violations = [v for v in check_grounding(answer, docs) if v["kind"] != "number"]
    if grounding_violations:
        detail = "; ".join(
            f"{v['claim']} near {'/'.join(v['incident_ids'])}" for v in grounding_violations[:5]
        )
        corrections.append(
            f"The following dates or incident references do not appear in the retrieved "
            f"text for that incident: {detail}. Re-check each against the source and "
            f"correct or remove it - do not restate it unchanged."
        )

    return corrections


def generate(question: str, docs: list[Document], index_block: str = "") -> tuple[str, list[Citation]]:
    chain = RAG_PROMPT | get_chat_model() | StrOutputParser()
    context = f"{index_block}\n\n{format_docs(docs)}" if index_block else format_docs(docs)
    answer = chain.invoke({"context": context, "question": question})
    grounded_half, _ = split_outside_knowledge(answer)
    citations = _resolve_citations(grounded_half, docs)

    is_dependency_answer = "### DEPENDENCY IMPACT ###" in index_block
    corrections = _find_corrections(answer, citations, docs, index_block, is_dependency_answer)

    if corrections:
        retry_question = f"{question}\n\nYour previous answer needs correction:\n" + "\n".join(
            f"- {correction}" for correction in corrections
        )
        answer = chain.invoke({"context": context, "question": retry_question})
        citations = _resolve_citations(split_outside_knowledge(answer)[0], docs)

    return answer, citations


def answer_question(question: str, strategy: str = "hybrid", k: int | None = None) -> RAGAnswer:
    settings = get_settings()
    resolved_k = k if k is not None else settings.retrieval_top_k

    start = time.perf_counter()
    docs, index_block, route = retrieve_for_question(question, strategy, resolved_k)
    answer, citations = generate(question, docs, index_block)
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
        route=route,
        used_outside_knowledge=OUTSIDE_KNOWLEDGE_MARKER in answer,
    )
