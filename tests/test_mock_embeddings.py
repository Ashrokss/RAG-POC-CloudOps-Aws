"""
Similarity is checked with a plain dot product, not numpy/scipy cosine
helpers, because _embed already L2-normalizes its output - dot product IS
cosine similarity once both vectors have unit norm, so recomputing that with
an extra numerics dependency would just restate what the mock guarantees.
"""

from __future__ import annotations

import math

from rag.embeddings.mock_embeddings import MockBedrockEmbeddings


def _dot(a: list[float], b: list[float]) -> float:
    return sum(x * y for x, y in zip(a, b))


def _norm(vector: list[float]) -> float:
    return math.sqrt(sum(component * component for component in vector))


def test_embed_query_returns_fixed_length_normalized_vector() -> None:
    embeddings = MockBedrockEmbeddings(dimension=128)

    vector = embeddings.embed_query("database connection pool exhausted")

    assert len(vector) == 128
    assert math.isclose(_norm(vector), 1.0, rel_tol=1e-9)


def test_embed_documents_returns_one_normalized_vector_per_text() -> None:
    embeddings = MockBedrockEmbeddings()
    texts = ["first incident report", "second incident report", "third report"]

    vectors = embeddings.embed_documents(texts)

    assert len(vectors) == len(texts)
    for vector in vectors:
        assert len(vector) == embeddings.dimension
        assert math.isclose(_norm(vector), 1.0, rel_tol=1e-9)


def test_shared_vocabulary_yields_higher_similarity_than_no_overlap() -> None:
    embeddings = MockBedrockEmbeddings()

    shared_a = embeddings.embed_query("connection pool exhausted timeout database")
    shared_b = embeddings.embed_query("connection pool exhausted retry database")
    unrelated = embeddings.embed_query("giraffe umbrella keyboard nebula xylophone")

    sim_shared = _dot(shared_a, shared_b)
    sim_unrelated = _dot(shared_a, unrelated)

    assert sim_shared > 0.0
    assert sim_shared > sim_unrelated
