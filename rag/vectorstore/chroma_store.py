"""
This is intentionally the only Chroma-aware module in the codebase - every
other module (ingestion CLI, retrieval, eval) calls get_vectorstore or
build_index and never imports langchain_chroma or chromadb directly, so
swapping the vector store later is a one-module change.

The reset path re-fetches a fresh Chroma handle after delete_collection()
rather than reusing the existing one: delete_collection() drops the
collection from the underlying chromadb client, so the old handle's cached
collection reference is now dangling and unsafe to add_documents against.

The upsert path deletes by id before adding unconditionally, without first
checking which ids already exist, because Chroma's delete() is a no-op for
ids that aren't present - one call handles both "new chunk" and "chunk whose
content changed since the last ingest" without a diff.
"""

from __future__ import annotations

import sys

try:
    # Debian bullseye (Azure App Service's Python base image) ships a system
    # sqlite3 older than the 3.35.0 chromadb requires - pysqlite3-binary
    # bundles a modern, self-contained SQLite build with no compiler needed.
    # Must happen before `from langchain_chroma import Chroma` below, since
    # that's what pulls in chromadb, which imports the stdlib sqlite3 module
    # this swap intercepts. No-ops on platforms whose system sqlite3 is
    # already new enough (Windows/macOS local dev), where pysqlite3-binary
    # isn't installed - see deploy/requirements-deploy.txt.
    import pysqlite3

    sys.modules["sqlite3"] = sys.modules.pop("pysqlite3")
except ImportError:
    pass

from langchain_chroma import Chroma
from langchain_core.documents import Document
from langchain_core.embeddings import Embeddings

from config.settings import get_settings
from rag.embeddings.factory import get_embeddings


def get_vectorstore(embedding_function: Embeddings) -> Chroma:
    settings = get_settings()
    return Chroma(
        collection_name=settings.chroma_collection_name,
        embedding_function=embedding_function,
        persist_directory=settings.chroma_persist_dir,
    )


def build_index(chunks: list[Document], reset: bool = False) -> Chroma:
    embedding_function = get_embeddings()
    vectorstore = get_vectorstore(embedding_function)

    if reset:
        vectorstore.delete_collection()
        vectorstore = get_vectorstore(embedding_function)

    if not chunks:
        return vectorstore

    ids = [chunk.metadata["chunk_id"] for chunk in chunks]
    if not reset:
        vectorstore.delete(ids=ids)
    vectorstore.add_documents(chunks, ids=ids)
    return vectorstore


def get_collection_stats(vectorstore: Chroma) -> dict[str, int]:
    return {"count": vectorstore._collection.count()}