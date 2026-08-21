"""
One row per incident document, built from the same corpus loader ingestion
uses. This is the structured half of the system: chunk metadata already
carries incident_id/section/severity/services/date/source, but nothing ever
queried it, so questions whose answer is a count, a ranking or a total had to
be inferred from whichever k chunks retrieval happened to surface.

Rows come from load_rca_documents rather than from the chunk list because
title, region, status, tags and the three aggregate fields
(detection_gap_minutes, duration_minutes, cost_usd) live on RCADocumentMeta
and were never copied onto chunks - copying them onto all 233 chunks to
reconstruct 25 rows would be the wrong direction.

A dict per row, not pandas and not a database: 25 rows, read once per process.
"""

from __future__ import annotations

from functools import lru_cache

from rag.ingestion.loader import CORPUS_DIRS, load_rca_documents

_ROW_FIELDS = (
    "doc_id",
    "incident_id",
    "title",
    "date",
    "severity",
    "services",
    "region",
    "status",
    "tags",
    "source",
    "detection_gap_minutes",
    "duration_minutes",
    "cost_usd",
)


@lru_cache(maxsize=1)
def incident_rows() -> tuple[dict, ...]:
    rows = []
    for meta, _body in load_rca_documents(list(CORPUS_DIRS)):
        row = {field: getattr(meta, field) for field in _ROW_FIELDS}
        row["date"] = meta.date.date().isoformat()
        rows.append(row)
    return tuple(sorted(rows, key=lambda row: row["date"]))


def reset_incident_table() -> None:
    incident_rows.cache_clear()


def filter_rows(rows: tuple[dict, ...], services: list[str]) -> tuple[dict, ...]:
    if not services:
        return rows
    wanted = set(services)
    return tuple(row for row in rows if wanted & set(row["services"]))


def render_rows(rows: tuple[dict, ...]) -> str:
    """Pipe-delimited, one incident per line - compact enough to hand the model
    the whole index without crowding out the retrieved chunk text."""
    lines = [
        "id | date | severity | services | status | detection_gap_min | duration_min | cost_usd | title"
    ]
    for row in rows:
        lines.append(
            " | ".join(
                [
                    row["incident_id"],
                    row["date"],
                    row["severity"],
                    ",".join(row["services"]),
                    row["status"],
                    _cell(row["detection_gap_minutes"]),
                    _cell(row["duration_minutes"]),
                    _cell(row["cost_usd"]),
                    row["title"],
                ]
            )
        )
    return "\n".join(lines)


def _cell(value: object) -> str:
    # "unknown", not a blank or a 0 - a missing detection gap must not read as
    # instant detection when the model ranks the column.
    return "unknown" if value is None else str(value)
