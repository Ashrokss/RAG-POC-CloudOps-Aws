"""
Cases are expressed as doc-id lists (never Document objects) because that's
the only shape recall_at_k/precision_at_k/mrr accept - see the module
docstring in eval/retrieval_metrics.py for why doc-id dedup happens upstream
of these functions rather than inside them.
"""

from __future__ import annotations

import pytest

from eval.retrieval_metrics import mrr, precision_at_k, recall_at_k

_CASE_IDS = ["exact_match", "partial_match", "no_match", "empty_relevant"]


@pytest.mark.parametrize(
    ("retrieved", "relevant", "expected"),
    [
        (["a", "b", "c"], ["a", "b", "c"], 1.0),
        (["x", "a", "y"], ["a", "b"], 0.5),
        (["x", "y", "z"], ["a", "b"], 0.0),
        (["a", "b"], [], 0.0),
    ],
    ids=_CASE_IDS,
)
def test_recall_at_k(retrieved: list[str], relevant: list[str], expected: float) -> None:
    assert recall_at_k(retrieved, relevant) == pytest.approx(expected)


@pytest.mark.parametrize(
    ("retrieved", "relevant", "expected"),
    [
        (["a", "b", "c"], ["a", "b", "c"], 1.0),
        (["x", "a", "y"], ["a", "b"], 1 / 3),
        (["x", "y", "z"], ["a", "b"], 0.0),
        (["a", "b"], [], 0.0),
    ],
    ids=_CASE_IDS,
)
def test_precision_at_k(retrieved: list[str], relevant: list[str], expected: float) -> None:
    assert precision_at_k(retrieved, relevant) == pytest.approx(expected)


@pytest.mark.parametrize(
    ("retrieved", "relevant", "expected"),
    [
        (["a", "b", "c"], ["a", "b", "c"], 1.0),
        (["x", "a", "y"], ["a", "b"], 0.5),
        (["x", "y", "z"], ["a", "b"], 0.0),
        (["a", "b"], [], 0.0),
    ],
    ids=_CASE_IDS,
)
def test_mrr(retrieved: list[str], relevant: list[str], expected: float) -> None:
    assert mrr(retrieved, relevant) == pytest.approx(expected)
