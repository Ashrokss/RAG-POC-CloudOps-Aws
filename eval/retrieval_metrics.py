"""
recall_at_k/precision_at_k/mrr all operate on doc-id lists rather than raw
Document objects: retrieve_only's callers already dedupe a retriever's chunk
hits down to unique doc_ids (see rag/chain/rag_chain.py's retrieved_doc_ids
construction), so scoring against doc_ids instead of chunks means a
multi-chunk hit on one relevant document is counted once, matching how a
golden question's relevant_doc_ids is itself a set of documents, not chunks.
"""

from __future__ import annotations


def recall_at_k(retrieved_doc_ids: list[str], relevant_doc_ids: list[str]) -> float:
    if not relevant_doc_ids:
        return 0.0
    hits = len(set(retrieved_doc_ids) & set(relevant_doc_ids))
    return hits / len(set(relevant_doc_ids))


def precision_at_k(retrieved_doc_ids: list[str], relevant_doc_ids: list[str]) -> float:
    if not retrieved_doc_ids:
        return 0.0
    hits = len(set(retrieved_doc_ids) & set(relevant_doc_ids))
    return hits / len(retrieved_doc_ids)


def mrr(retrieved_doc_ids: list[str], relevant_doc_ids: list[str]) -> float:
    relevant = set(relevant_doc_ids)
    for rank, doc_id in enumerate(retrieved_doc_ids, start=1):
        if doc_id in relevant:
            return 1.0 / rank
    return 0.0


def aggregate_metrics(records: list[dict]) -> dict:
    groups: dict[tuple[str, str], list[dict]] = {}
    for record in records:
        key = (record["strategy"], record["question_type"])
        groups.setdefault(key, []).append(record)

    aggregated: dict[tuple[str, str], dict[str, float]] = {}
    for key, group_records in groups.items():
        numeric_fields = [
            field
            for field, value in group_records[0].items()
            if isinstance(value, (int, float)) and not isinstance(value, bool)
        ]
        averages = {
            field: sum(r[field] for r in group_records) / len(group_records) for field in numeric_fields
        }
        averages["n"] = len(group_records)
        aggregated[key] = averages

    return aggregated