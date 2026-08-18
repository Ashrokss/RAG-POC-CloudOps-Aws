"""
Chunking runs in two passes because either pass alone breaks retrieval in a
different way. Splitting only on `##` headers keeps citations pointing at a
meaningful section (Root Cause, Timeline, ...) instead of an arbitrary
character offset, but a section like Timeline can run well past chunk_size
for a long incident. Splitting only by character count would satisfy the
size bound but chop mid-section, mixing (or losing) the section label a
citation depends on. Running the recursive splitter per-section, only on
sections that actually exceed chunk_size, gets both.
"""

from __future__ import annotations

import hashlib

from langchain_core.documents import Document
from langchain_text_splitters import MarkdownHeaderTextSplitter, RecursiveCharacterTextSplitter

from rag.models import RCADocumentMeta

_HEADER_SPLITTER = MarkdownHeaderTextSplitter(headers_to_split_on=[("##", "section")])


def _chunk_id(doc_id: str, section: str, ordinal: int) -> str:
    """Derived from the document, its section, and the chunk's position in that
    document rather than minted from uuid4() per call. A random id meant the
    same chunk carried one id inside Chroma and a different one every time
    retrieval re-chunked the corpus in memory, which (a) made the upsert path
    in rag/vectorstore/chroma_store.py a no-op delete followed by an insert
    under a brand-new id, so a second `ingest run` without --reset duplicated
    the whole corpus, and (b) made any per-chunk caching, dedup against the
    vector store, or chunk-level feedback impossible to key."""
    digest = hashlib.sha1(f"{doc_id}|{section}|{ordinal}".encode("utf-8")).hexdigest()
    return digest[:16]


def chunk_document(meta: RCADocumentMeta, body: str, chunk_size: int, chunk_overlap: int) -> list[Document]:
    recursive_splitter = RecursiveCharacterTextSplitter(chunk_size=chunk_size, chunk_overlap=chunk_overlap)

    chunks: list[Document] = []
    ordinal = 0
    for section_doc in _HEADER_SPLITTER.split_text(body):
        section = section_doc.metadata["section"]
        text = section_doc.page_content
        section_texts = [text] if len(text) <= chunk_size else recursive_splitter.split_text(text)

        for section_text in section_texts:
            chunks.append(
                Document(
                    page_content=section_text,
                    metadata={
                        "chunk_id": _chunk_id(meta.doc_id, section, ordinal),
                        "doc_id": meta.doc_id,
                        "incident_id": meta.incident_id,
                        "section": section,
                        "severity": meta.severity,
                        "services": ",".join(meta.services),
                        "date": meta.date.isoformat(),
                        "source": meta.source,
                    },
                )
            )
            ordinal += 1
    return chunks


def chunk_all(docs: list[tuple[RCADocumentMeta, str]], chunk_size: int, chunk_overlap: int) -> list[Document]:
    return [chunk for meta, body in docs for chunk in chunk_document(meta, body, chunk_size, chunk_overlap)]