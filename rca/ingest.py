"""
Bulk dump and single document take the same path. There is no "import mode":
an adapter turns bytes into a SourceDoc, and everything after that is shared,
so a corpus loaded from disk and a knowledge card promoted five minutes ago
are indexed by identical code.

Chunking is two-pass. Splitting only on '##' headers keeps a citation pointing
at a meaningful section (Root Cause, Timeline) instead of a character offset,
but a Timeline for a long incident runs past any sane chunk size. Splitting
only by size satisfies the bound and destroys the section label a citation
depends on. Header-split first, size-split only the sections that overflow.
"""

from __future__ import annotations

import re
from datetime import datetime, timezone
from pathlib import Path

import frontmatter

from rca.models import Chunk, SourceDoc, stable_id, utc_now
from rca.providers import Embedder, get_embedder
from rca.vocabulary import canonical_all
from rca.store import Store

CHUNK_SIZE = 800
CHUNK_OVERLAP = 120
_HEADER_RE = re.compile(r"^##\s+(.+?)\s*$", re.MULTILINE)


def _as_utc(value: object) -> datetime | None:
    if isinstance(value, datetime):
        return value if value.tzinfo else value.replace(tzinfo=timezone.utc)
    if isinstance(value, str) and value:
        try:
            parsed = datetime.fromisoformat(value.replace("Z", "+00:00"))
        except ValueError:
            return None
        return parsed if parsed.tzinfo else parsed.replace(tzinfo=timezone.utc)
    return None


def markdown_adapter(path: Path, plane: str = "evidence", tier: str = "internal") -> SourceDoc:
    """python-frontmatter, not a hand-rolled '---' split: YAML values here
    routinely contain colons, quotes and nested lists that a naive split
    mangles."""
    meta, body = frontmatter.parse(path.read_text(encoding="utf-8"))
    incident_id = meta.get("incident_id")
    return SourceDoc(
        # doc_id from the source URI, not a uuid: re-ingesting the same file
        # must update the same row rather than duplicate it.
        doc_id=stable_id(path.as_posix()),
        source_uri=path.as_posix(),
        plane=plane,  # type: ignore[arg-type]
        source_tier=tier,  # type: ignore[arg-type]
        title=str(meta.get("title") or path.stem),
        body=body,
        incident_id=str(incident_id) if incident_id else None,
        date=_as_utc(meta.get("date")),
        severity=meta.get("severity"),
        # Normalised here, at the only place raw frontmatter enters the system.
        services=canonical_all([str(s) for s in (meta.get("services") or [])]),
        region=meta.get("region"),
        status=meta.get("status"),
        tags=[str(t) for t in (meta.get("tags") or [])],
        detection_gap_minutes=meta.get("detection_gap_minutes"),
        duration_minutes=meta.get("duration_minutes"),
        cost_usd=meta.get("cost_usd"),
    )


def _split_sections(body: str) -> list[tuple[str, str]]:
    matches = list(_HEADER_RE.finditer(body))
    if not matches:
        return [("Body", body.strip())] if body.strip() else []
    sections = []
    for i, match in enumerate(matches):
        end = matches[i + 1].start() if i + 1 < len(matches) else len(body)
        text = body[match.end() : end].strip()
        if text:
            sections.append((match.group(1), text))
    return sections


def _split_size(text: str, size: int, overlap: int) -> list[str]:
    if len(text) <= size:
        return [text]

    parts: list[str] = []
    start = 0
    while True:
        window = text[start : start + size]
        reached_end = start + size >= len(text)
        # Break on whitespace so a chunk boundary never lands mid-token - but
        # never on the final window, which has no following text to break from.
        if not reached_end:
            cut = window.rfind(" ")
            if cut > size // 2:
                window = window[:cut]

        # A continuation window starts wherever the previous one ended, which
        # is mid-token as often as not - "connection-count" arrived as
        # "n-count" and the model quoted it back that way. Drop the partial
        # leading word; the overlap means nothing is lost.
        if start > 0 and " " in window:
            window = window[window.index(" ") + 1 :]

        stripped = window.strip()
        if stripped:
            parts.append(stripped)
        if reached_end:
            break
        # Advance past this window minus the overlap. Without the break above,
        # a tail shorter than `overlap` advanced by a handful of characters per
        # iteration and emitted a near-duplicate chunk for each one: 25 docs
        # produced 5,754 chunks instead of ~200.
        start += max(len(window) - overlap, 1)
    return parts


def chunk_doc(doc: SourceDoc, size: int = CHUNK_SIZE, overlap: int = CHUNK_OVERLAP) -> list[Chunk]:
    chunks: list[Chunk] = []
    ordinal = 0
    for section, text in _split_sections(doc.body):
        for part in _split_size(text, size, overlap):
            chunks.append(
                Chunk(
                    chunk_id=stable_id(doc.doc_id, section, ordinal),
                    doc_id=doc.doc_id,
                    section=section,
                    ordinal=ordinal,
                    text=part,
                    incident_id=doc.incident_id,
                    plane=doc.plane,
                    source_tier=doc.source_tier,
                    services=doc.services,
                )
            )
            ordinal += 1
    return chunks


def ingest_doc(store: Store, doc: SourceDoc, embedder: Embedder, ingest_run: str) -> int:
    store.upsert_doc(doc, ingest_run)
    chunks = chunk_doc(doc)
    if not chunks:
        return 0
    # search_text, not text: the chunk's identity has to be embedded with it.
    vectors = embedder.embed([c.search_text for c in chunks])
    store.replace_chunks(doc.doc_id, chunks, vectors, embedder.model_id)
    store.audit("ingest", "doc_indexed", doc.doc_id, f"{len(chunks)} chunks from {doc.source_uri}")
    return len(chunks)


def ingest_paths(
    store: Store,
    paths: list[Path],
    embedder: Embedder | None = None,
    plane: str = "evidence",
    tier: str = "internal",
) -> dict[str, int]:
    embedder = embedder or get_embedder()
    run = stable_id(utc_now().isoformat(), len(paths))
    docs = chunks = 0
    for path in sorted(paths):
        if path.name.lower() == "readme.md" or path.name.startswith("_"):
            continue
        added = ingest_doc(store, markdown_adapter(path, plane, tier), embedder, run)
        docs += 1
        chunks += added
    return {"docs": docs, "chunks": chunks}


def ingest_dirs(store: Store, dirs: list[Path], **kwargs) -> dict[str, int]:
    paths = [p for d in dirs for p in sorted(Path(d).glob("*.md"))]
    return ingest_paths(store, paths, **kwargs)
