"""
One store for vectors, metadata, the review queue and the audit log.

SQLite here, Postgres+pgvector in production - the schema below is written to
survive that swap: same tables, same columns, and the only backend-specific
code is `_search_vectors`, which brute-forces cosine over stored float32
blobs. At this corpus size (hundreds to low thousands of chunks) that is
microseconds and needs no index; past that, the swap is `embedding vector(N)`
plus an ivfflat index and an `ORDER BY embedding <=> query` - the surrounding
code does not change.

Why one relational store rather than a vector DB plus a database: the
predecessor learned this the expensive way. Half its hard questions were SQL -
"which incident had the longest detection gap" is a max over a column, "what
breaks if vpc fails" is a graph walk - and a vector store answers neither, so
it grew a hand-rolled in-memory table alongside. The review queue also wants
transactions, and the audit log wants to be diffable and durable.

Every write that changes what the system believes goes through `audit()`.

The connection is opened with check_same_thread=False and writes are guarded
by a lock, because a web front end runs each request on a different thread
from the one that opened the store - and sqlite3's default thread check
rejects that outright. Reads rely on SQLite's own serialised threading mode;
writes take the lock so two concurrent promotions cannot interleave.
"""

from __future__ import annotations

import json
import sqlite3
import threading
from collections.abc import Iterable, Sequence
from datetime import datetime
from pathlib import Path
from typing import Any, Optional

import numpy as np

from rca.models import (
    CandidateCard,
    Chunk,
    KnowledgeGap,
    Retrieved,
    SourceDoc,
    Verdict,
    utc_now,
)

_SCHEMA = """
CREATE TABLE IF NOT EXISTS docs (
    doc_id TEXT PRIMARY KEY,
    source_uri TEXT NOT NULL,
    plane TEXT NOT NULL,
    source_tier TEXT NOT NULL,
    title TEXT NOT NULL,
    body TEXT NOT NULL,
    incident_id TEXT,
    date TEXT,
    severity TEXT,
    services TEXT NOT NULL DEFAULT '[]',
    region TEXT,
    status TEXT,
    tags TEXT NOT NULL DEFAULT '[]',
    detection_gap_minutes INTEGER,
    duration_minutes INTEGER,
    cost_usd REAL,
    content_hash TEXT NOT NULL,
    retrieved_at TEXT NOT NULL,
    review_ttl_days INTEGER,
    ingest_run TEXT
);
CREATE INDEX IF NOT EXISTS docs_incident ON docs(incident_id);
CREATE INDEX IF NOT EXISTS docs_plane ON docs(plane);

CREATE TABLE IF NOT EXISTS chunks (
    chunk_id TEXT PRIMARY KEY,
    doc_id TEXT NOT NULL REFERENCES docs(doc_id) ON DELETE CASCADE,
    section TEXT NOT NULL,
    ordinal INTEGER NOT NULL,
    text TEXT NOT NULL,
    incident_id TEXT,
    label TEXT NOT NULL DEFAULT '',
    plane TEXT NOT NULL,
    source_tier TEXT NOT NULL,
    services TEXT NOT NULL DEFAULT '[]',
    embedding BLOB,
    embedding_model TEXT
);
CREATE INDEX IF NOT EXISTS chunks_doc ON chunks(doc_id);
CREATE INDEX IF NOT EXISTS chunks_plane ON chunks(plane);

CREATE TABLE IF NOT EXISTS gaps (
    gap_id TEXT PRIMARY KEY,
    question TEXT NOT NULL,
    reason TEXT NOT NULL,
    best_score REAL NOT NULL DEFAULT 0,
    hit_count INTEGER NOT NULL DEFAULT 1,
    status TEXT NOT NULL,
    first_seen TEXT NOT NULL,
    last_seen TEXT NOT NULL
);

CREATE TABLE IF NOT EXISTS candidates (
    candidate_id TEXT PRIMARY KEY,
    gap_id TEXT NOT NULL REFERENCES gaps(gap_id),
    claim TEXT NOT NULL,
    applies_to TEXT NOT NULL DEFAULT '[]',
    failure_mode TEXT,
    evidence TEXT NOT NULL DEFAULT '[]',
    confidence REAL NOT NULL DEFAULT 0,
    status TEXT NOT NULL,
    verdict TEXT,
    created_at TEXT NOT NULL,
    reviewed_by TEXT,
    review_reason TEXT
);

CREATE TABLE IF NOT EXISTS audit (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    ts TEXT NOT NULL,
    actor TEXT NOT NULL,
    action TEXT NOT NULL,
    subject_id TEXT NOT NULL,
    detail TEXT NOT NULL DEFAULT ''
);
"""


def _dumps(value: Any) -> str:
    return json.dumps(value, default=str)


def _vec_to_blob(vector: Sequence[float]) -> bytes:
    return np.asarray(vector, dtype=np.float32).tobytes()


def _blob_to_vec(blob: bytes) -> np.ndarray:
    return np.frombuffer(blob, dtype=np.float32)


class EmbeddingMismatchError(RuntimeError):
    """The index was built by a different embedder than the one querying it."""


class Store:
    def __init__(self, path: str | Path = "data/rca.db") -> None:
        self.path = str(path)
        if self.path != ":memory:":
            Path(self.path).parent.mkdir(parents=True, exist_ok=True)
        self.conn = sqlite3.connect(self.path, check_same_thread=False)
        self.conn.row_factory = sqlite3.Row
        self._lock = threading.RLock()
        self.conn.executescript(_SCHEMA)
        self.conn.execute("PRAGMA foreign_keys = ON")
        self.conn.commit()

    def close(self) -> None:
        self.conn.close()

    # ---------- audit ----------

    def audit(self, actor: str, action: str, subject_id: str, detail: str = "") -> None:
        with self._lock:
            self.conn.execute(
                "INSERT INTO audit (ts, actor, action, subject_id, detail) VALUES (?,?,?,?,?)",
                (utc_now().isoformat(), actor, action, subject_id, detail),
            )
            self.conn.commit()

    def audit_trail(self, subject_id: Optional[str] = None) -> list[dict]:
        if subject_id:
            rows = self.conn.execute(
                "SELECT * FROM audit WHERE subject_id = ? ORDER BY id", (subject_id,)
            ).fetchall()
        else:
            rows = self.conn.execute("SELECT * FROM audit ORDER BY id").fetchall()
        return [dict(row) for row in rows]

    # ---------- docs and chunks ----------

    def upsert_doc(self, doc: SourceDoc, ingest_run: str) -> None:
        with self._lock:
            self.conn.execute(
                """INSERT INTO docs (doc_id, source_uri, plane, source_tier, title, body, incident_id,
                                     date, severity, services, region, status, tags,
                                     detection_gap_minutes, duration_minutes, cost_usd,
                                     content_hash, retrieved_at, review_ttl_days, ingest_run)
                   VALUES (?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?)
                   ON CONFLICT(doc_id) DO UPDATE SET
                     source_uri=excluded.source_uri, plane=excluded.plane,
                     source_tier=excluded.source_tier, title=excluded.title, body=excluded.body,
                     incident_id=excluded.incident_id, date=excluded.date, severity=excluded.severity,
                     services=excluded.services, region=excluded.region, status=excluded.status,
                     tags=excluded.tags, detection_gap_minutes=excluded.detection_gap_minutes,
                     duration_minutes=excluded.duration_minutes, cost_usd=excluded.cost_usd,
                     content_hash=excluded.content_hash, retrieved_at=excluded.retrieved_at,
                     review_ttl_days=excluded.review_ttl_days, ingest_run=excluded.ingest_run""",
                (
                    doc.doc_id, doc.source_uri, doc.plane, doc.source_tier, doc.title, doc.body,
                    doc.incident_id, doc.date.isoformat() if doc.date else None, doc.severity,
                    _dumps(doc.services), doc.region, doc.status, _dumps(doc.tags),
                    doc.detection_gap_minutes, doc.duration_minutes, doc.cost_usd,
                    doc.content_hash, doc.retrieved_at.isoformat(), doc.review_ttl_days, ingest_run,
                ),
            )
            self.conn.commit()

    def replace_chunks(
        self, doc_id: str, chunks: Iterable[Chunk], vectors: Sequence[Sequence[float]], model: str
    ) -> int:
        """Delete-then-insert per document rather than per chunk: a re-ingest
        whose sections changed must not leave orphaned chunks behind from the
        previous shape of the document."""
        chunks = list(chunks)
        with self._lock:
            self._replace_chunks(doc_id, chunks, vectors, model)
        return len(chunks)

    def _replace_chunks(self, doc_id, chunks, vectors, model) -> None:
        self.conn.execute("DELETE FROM chunks WHERE doc_id = ?", (doc_id,))
        self.conn.executemany(
            """INSERT INTO chunks (chunk_id, doc_id, section, ordinal, text, incident_id,
                                   label, plane, source_tier, services, embedding, embedding_model)
               VALUES (?,?,?,?,?,?,?,?,?,?,?,?)""",
            [
                (
                    c.chunk_id, c.doc_id, c.section, c.ordinal, c.text, c.incident_id,
                    c.label, c.plane, c.source_tier, _dumps(c.services), _vec_to_blob(v), model,
                )
                for c, v in zip(chunks, vectors)
            ],
        )
        self.conn.commit()

    def embedding_models(self) -> set[str]:
        """More than one model in here means the vectors are not comparable -
        callers refuse rather than return silent nonsense. The predecessor
        shipped an index built by one embedder into an app querying with
        another and surfaced it as a raw dimension error in the UI."""
        rows = self.conn.execute(
            "SELECT DISTINCT embedding_model FROM chunks WHERE embedding_model IS NOT NULL"
        ).fetchall()
        return {row[0] for row in rows}

    def counts(self) -> dict[str, int]:
        out = {}
        for table in ("docs", "chunks", "gaps", "candidates"):
            out[table] = self.conn.execute(f"SELECT COUNT(*) FROM {table}").fetchone()[0]
        return out

    def _row_to_chunk(self, row: sqlite3.Row) -> Chunk:
        return Chunk(
            chunk_id=row["chunk_id"], doc_id=row["doc_id"], section=row["section"],
            ordinal=row["ordinal"], text=row["text"], incident_id=row["incident_id"],
            label=row["label"] if "label" in row.keys() else "",
            plane=row["plane"], source_tier=row["source_tier"],
            services=json.loads(row["services"]),
        )

    def all_chunks(self, planes: Sequence[str] = ("evidence", "concept")) -> list[Chunk]:
        marks = ",".join("?" * len(planes))
        rows = self.conn.execute(
            f"SELECT * FROM chunks WHERE plane IN ({marks}) ORDER BY doc_id, ordinal", tuple(planes)
        ).fetchall()
        return [self._row_to_chunk(row) for row in rows]

    def assert_embedding_match(self, model_id: str) -> None:
        """Refuse to search with an embedder the index was not built by.

        Recording the model is not enough - nothing consulted it, and a 256-dim
        query against 1536-dim vectors surfaced as a numpy matmul error from
        three frames deep. Worse is the case where the dimensions happen to
        agree: the search then returns confident nonsense with no error at all.
        """
        built_with = self.embedding_models()
        if not built_with or built_with == {model_id}:
            return
        raise EmbeddingMismatchError(
            f"index was built with {sorted(built_with)} but this process embeds queries with "
            f"{model_id!r}. Vectors from different models are not comparable. Re-run "
            "`python -m rca.cli ingest --reset` with the provider you intend to query with."
        )

    def search_vectors(
        self, query_vector: Sequence[float], k: int, planes: Sequence[str] = ("evidence", "concept")
    ) -> list[Retrieved]:
        """Cosine over stored vectors. Candidate-plane chunks are excluded by
        default and must be asked for explicitly - unpromoted knowledge is not
        allowed to leak into an answer."""
        marks = ",".join("?" * len(planes))
        rows = self.conn.execute(
            f"SELECT * FROM chunks WHERE plane IN ({marks}) AND embedding IS NOT NULL", tuple(planes)
        ).fetchall()
        if not rows:
            return []

        matrix = np.vstack([_blob_to_vec(row["embedding"]) for row in rows])
        query = np.asarray(query_vector, dtype=np.float32)
        norms = np.linalg.norm(matrix, axis=1) * (np.linalg.norm(query) or 1.0)
        scores = np.divide(matrix @ query, np.where(norms == 0, 1.0, norms))

        top = np.argsort(-scores)[:k]
        return [Retrieved(chunk=self._row_to_chunk(rows[i]), score=float(scores[i])) for i in top]

    # ---------- incident table (the structured half) ----------

    def incidents(self, services: Sequence[str] = ()) -> list[dict]:
        sql = "SELECT * FROM docs WHERE incident_id IS NOT NULL AND plane = 'evidence'"
        rows = [dict(row) for row in self.conn.execute(sql).fetchall()]
        for row in rows:
            row["services"] = json.loads(row["services"])
            row["tags"] = json.loads(row["tags"])
        if services:
            wanted = set(services)
            rows = [row for row in rows if wanted & set(row["services"])]
        return sorted(rows, key=lambda row: row["date"] or "")

    # ---------- gaps ----------

    def record_gap(self, gap: KnowledgeGap) -> KnowledgeGap:
        """Same question asked twice is one gap with a hit count, not two rows -
        the count is the prioritisation signal for which gap to research first."""
        with self._lock:
            return self._record_gap(gap)

    def _record_gap(self, gap: KnowledgeGap) -> KnowledgeGap:
        existing = self.conn.execute(
            "SELECT * FROM gaps WHERE gap_id = ?", (gap.gap_id,)
        ).fetchone()
        if existing:
            self.conn.execute(
                "UPDATE gaps SET hit_count = hit_count + 1, last_seen = ? WHERE gap_id = ?",
                (utc_now().isoformat(), gap.gap_id),
            )
            self.conn.commit()
            return self.get_gap(gap.gap_id)  # type: ignore[return-value]

        self.conn.execute(
            """INSERT INTO gaps (gap_id, question, reason, best_score, hit_count, status,
                                 first_seen, last_seen) VALUES (?,?,?,?,?,?,?,?)""",
            (
                gap.gap_id, gap.question, gap.reason, gap.best_score, gap.hit_count,
                gap.status, gap.first_seen.isoformat(), gap.last_seen.isoformat(),
            ),
        )
        self.conn.commit()
        self.audit("system", "gap_opened", gap.gap_id, gap.question[:200])
        return gap

    def get_gap(self, gap_id: str) -> Optional[KnowledgeGap]:
        row = self.conn.execute("SELECT * FROM gaps WHERE gap_id = ?", (gap_id,)).fetchone()
        return self._row_to_gap(row) if row else None

    def _row_to_gap(self, row: sqlite3.Row) -> KnowledgeGap:
        return KnowledgeGap(
            gap_id=row["gap_id"], question=row["question"], reason=row["reason"],
            best_score=row["best_score"], hit_count=row["hit_count"], status=row["status"],
            first_seen=datetime.fromisoformat(row["first_seen"]),
            last_seen=datetime.fromisoformat(row["last_seen"]),
        )

    def gaps(self, status: Optional[str] = None) -> list[KnowledgeGap]:
        if status:
            rows = self.conn.execute(
                "SELECT * FROM gaps WHERE status = ? ORDER BY hit_count DESC, first_seen", (status,)
            ).fetchall()
        else:
            rows = self.conn.execute(
                "SELECT * FROM gaps ORDER BY hit_count DESC, first_seen"
            ).fetchall()
        return [self._row_to_gap(row) for row in rows]

    def set_gap_status(self, gap_id: str, status: str) -> None:
        with self._lock:
            self.conn.execute("UPDATE gaps SET status = ? WHERE gap_id = ?", (status, gap_id))
            self.conn.commit()

    # ---------- candidates ----------

    def save_candidate(self, card: CandidateCard) -> None:
        with self._lock:
            self.conn.execute(
                """INSERT INTO candidates (candidate_id, gap_id, claim, applies_to, failure_mode,
                                           evidence, confidence, status, verdict, created_at,
                                           reviewed_by, review_reason)
                   VALUES (?,?,?,?,?,?,?,?,?,?,?,?)
                   ON CONFLICT(candidate_id) DO UPDATE SET
                     claim=excluded.claim, applies_to=excluded.applies_to,
                     failure_mode=excluded.failure_mode, evidence=excluded.evidence,
                     confidence=excluded.confidence, status=excluded.status,
                     verdict=excluded.verdict, reviewed_by=excluded.reviewed_by,
                     review_reason=excluded.review_reason""",
                (
                    card.candidate_id, card.gap_id, card.claim, _dumps(card.applies_to),
                    card.failure_mode, _dumps([e.model_dump() for e in card.evidence]),
                    card.confidence, card.status,
                    card.verdict.model_dump_json() if card.verdict else None,
                    card.created_at.isoformat(), card.reviewed_by, card.review_reason,
                ),
            )
            self.conn.commit()

    def _row_to_candidate(self, row: sqlite3.Row) -> CandidateCard:
        return CandidateCard(
            candidate_id=row["candidate_id"], gap_id=row["gap_id"], claim=row["claim"],
            applies_to=json.loads(row["applies_to"]), failure_mode=row["failure_mode"],
            evidence=json.loads(row["evidence"]), confidence=row["confidence"],
            status=row["status"],
            verdict=Verdict.model_validate_json(row["verdict"]) if row["verdict"] else None,
            created_at=datetime.fromisoformat(row["created_at"]),
            reviewed_by=row["reviewed_by"], review_reason=row["review_reason"],
        )

    def candidates(self, status: Optional[str] = None) -> list[CandidateCard]:
        if status:
            rows = self.conn.execute(
                "SELECT * FROM candidates WHERE status = ? ORDER BY created_at", (status,)
            ).fetchall()
        else:
            rows = self.conn.execute("SELECT * FROM candidates ORDER BY created_at").fetchall()
        return [self._row_to_candidate(row) for row in rows]

    def get_candidate(self, candidate_id: str) -> Optional[CandidateCard]:
        row = self.conn.execute(
            "SELECT * FROM candidates WHERE candidate_id = ?", (candidate_id,)
        ).fetchone()
        return self._row_to_candidate(row) if row else None
