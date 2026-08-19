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

import uuid

from langchain_core.documents import Document
from langchain_text_splitters import MarkdownHeaderTextSplitter, RecursiveCharacterTextSplitter

from rag.models import RCADocumentMeta

_HEADER_SPLITTER = MarkdownHeaderTextSplitter(headers_to_split_on=[("##", "section")])


def chunk_document(meta: RCADocumentMeta, body: str, chunk_size: int, chunk_overlap: int) -> list[Document]:
    recursive_splitter = RecursiveCharacterTextSplitter(chunk_size=chunk_size, chunk_overlap=chunk_overlap)

    chunks: list[Document] = []
    for section_doc in _HEADER_SPLITTER.split_text(body):
        section = section_doc.metadata["section"]
        text = section_doc.page_content
        section_texts = [text] if len(text) <= chunk_size else recursive_splitter.split_text(text)

        for section_text in section_texts:
            chunks.append(
                Document(
                    page_content=section_text,
                    metadata={
                        "chunk_id": str(uuid.uuid4()),
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
    return chunks


def chunk_all(docs: list[tuple[RCADocumentMeta, str]], chunk_size: int, chunk_overlap: int) -> list[Document]:
    return [chunk for meta, body in docs for chunk in chunk_document(meta, body, chunk_size, chunk_overlap)]