"""
Hybrid retrieval with a hard k cap and a coverage score.

The cap is a contract, not a hint. Its predecessor fused two k-wide rankings
and truncated nothing, so the hybrid strategy quietly answered from double the
context of every other strategy while being penalised on precision for the
same reason - every comparison it produced was invalid.

Coverage is the number the gap detector reads. It is the top semantic score,
which is a blunt instrument, but a blunt instrument that fires is worth more
than a subtle one that never does: what matters is that "the corpus does not
contain this" becomes a value the system can branch on.
"""

from __future__ import annotations

import re
from collections import defaultdict
from dataclasses import dataclass

from rank_bm25 import BM25Okapi

from rca.models import Chunk, Retrieved
from rca.providers import Embedder
from rca.store import Store

_TOKEN_RE = re.compile(r"[a-z0-9]+(?:-[a-z0-9]+)*")


def tokenize(text: str) -> list[str]:
    """Hyphens stay inside a token so INC-2025-0101 and checkout-order-processor
    remain single matchable units instead of splintering into 2025/0101."""
    return _TOKEN_RE.findall(text.lower())


@dataclass
class RetrievalResult:
    hits: list[Retrieved]
    coverage: float

    @property
    def chunks(self) -> list[Chunk]:
        return [hit.chunk for hit in self.hits]


class Retriever:
    def __init__(self, store: Store, embedder: Embedder) -> None:
        self.store = store
        self.embedder = embedder
        # Fail here, at construction, rather than three frames into numpy on
        # the first query.
        store.assert_embedding_match(embedder.model_id)
        self._bm25: BM25Okapi | None = None
        self._bm25_chunks: list[Chunk] = []

    def _keyword_index(self) -> tuple[BM25Okapi, list[Chunk]]:
        # Built once per process. BM25 has no persisted form, and rebuilding it
        # per query was the single largest cost in the predecessor: an eval of
        # 88 questions x 4 strategies paid for it 352 times.
        if self._bm25 is None:
            self._bm25_chunks = self.store.all_chunks()
            self._bm25 = BM25Okapi([tokenize(c.search_text) for c in self._bm25_chunks] or [[""]])
        return self._bm25, self._bm25_chunks

    def invalidate(self) -> None:
        """Called after anything is promoted into the store - a stale keyword
        index is how newly approved knowledge stays invisible."""
        self._bm25 = None

    def semantic(self, question: str, k: int) -> list[Retrieved]:
        vector = self.embedder.embed([question])[0]
        return self.store.search_vectors(vector, k)

    def keyword(self, question: str, k: int) -> list[Retrieved]:
        bm25, chunks = self._keyword_index()
        if not chunks:
            return []
        scores = bm25.get_scores(tokenize(question))
        top = sorted(range(len(chunks)), key=lambda i: -scores[i])[:k]
        best = max(scores) or 1.0
        return [Retrieved(chunk=chunks[i], score=float(scores[i] / best)) for i in top]

    def hybrid(self, question: str, k: int) -> RetrievalResult:
        """Reciprocal-rank fusion, then truncate to k. RRF because the two
        score scales are not comparable - blending them directly would let
        whichever scale happens to be wider decide the ranking."""
        semantic = self.semantic(question, k * 2)
        keyword = self.keyword(question, k * 2)

        fused: dict[str, float] = defaultdict(float)
        by_id: dict[str, Chunk] = {}
        for ranking in (semantic, keyword):
            for rank, hit in enumerate(ranking, start=1):
                fused[hit.chunk.chunk_id] += 1.0 / (60 + rank)
                by_id[hit.chunk.chunk_id] = hit.chunk

        ordered = sorted(fused.items(), key=lambda kv: -kv[1])[:k]
        hits = [Retrieved(chunk=by_id[cid], score=score) for cid, score in ordered]
        # Coverage comes from the semantic ranking, not the fused score: RRF
        # scores are rank artefacts and say nothing about whether anything
        # relevant was found.
        coverage = semantic[0].score if semantic else 0.0
        return RetrievalResult(hits=hits, coverage=coverage)

    def similar_incidents(self, symptom: str, k: int = 5, services: list[str] | None = None) -> list[str]:
        """Symptom-keyed, not question-keyed: finding a similar past incident is
        a different query from answering a question about one, and phrasing the
        symptom as a sentence only adds noise."""
        hits = self.semantic(symptom, k * 4)
        wanted = set(services or [])
        seen: list[str] = []
        for hit in hits:
            incident = hit.chunk.incident_id
            if not incident or incident in seen:
                continue
            if wanted and not wanted & set(hit.chunk.services):
                continue
            seen.append(incident)
            if len(seen) == k:
                break
        return seen
