"""
This is intentionally the only Chroma-aware module in the codebase - every
other module (ingestion CLI, retrieval, eval) calls get_vectorstore or
build_index and never imports langchain_chroma or chromadb directly, so
swapping the vector store later is a one-module change.

The reset path re-fetches a fresh Chroma handle after delete_collection()
rather than reusing the existing one: delete_collection() drops the
collection from the underlying chromadb client, so the old handle's cached
collection reference is now dangling and unsafe to add_documents against.

The collection records which embedder built it, and every read verifies it.
Without that, pointing a live app with a real embedding deployment at an index
built under mock embeddings surfaces as "Collection expecting embedding with
dimension of 256, got 1536" from deep inside Chroma, once per strategy, in the
UI - which is what happened on the deployed console. Worse is the case where
the dimensions happen to match: retrieval then returns confident nonsense with
no error at all. The check turns both into one message naming the two models
and the command that fixes it.

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
from rag.embeddings.factory import embedding_model_id, get_embeddings

_EMBEDDING_MODEL_KEY = "embedding_model"


class EmbeddingMismatchError(RuntimeError):
    """The collection was built by a different embedder than the one querying."""


def get_vectorstore(embedding_function: Embeddings, verify: bool = True) -> Chroma:
    settings = get_settings()
    vectorstore = Chroma(
        collection_name=settings.chroma_collection_name,
        embedding_function=embedding_function,
        persist_directory=settings.chroma_persist_dir,
    )
    if verify:
        _verify_embedding_model(vectorstore)
    return vectorstore


def _verify_embedding_model(vectorstore: Chroma) -> None:
    metadata = vectorstore._collection.metadata or {}
    built_with = metadata.get(_EMBEDDING_MODEL_KEY)
    current = embedding_model_id()

    # An index built before this stamp existed carries no provenance; refusing
    # to read it would break every existing deployment for no safety gain, so
    # an unstamped collection is allowed through and re-stamped on next ingest.
    if built_with is None or built_with == current:
        return

    raise EmbeddingMismatchError(
        f"Collection {vectorstore._collection.name!r} was indexed with "
        f"{built_with!r} but this process embeds queries with {current!r}. "
        "Vectors from different models are not comparable. Re-index with "
        "`python -m cli.ingest run --reset` using the current provider, or "
        "point the app back at the embedding model that built it."
    )


def build_index(chunks: list[Document], reset: bool = False) -> Chroma:
    embedding_function = get_embeddings()
    # verify=False on the write path: a rebuild is exactly how a mismatch gets
    # fixed, so refusing to open the collection would leave no way out of it.
    vectorstore = get_vectorstore(embedding_function, verify=False)

    if reset:
        vectorstore.delete_collection()
        vectorstore = get_vectorstore(embedding_function, verify=False)

    if not chunks:
        _stamp_embedding_model(vectorstore)
        return vectorstore

    ids = [chunk.metadata["chunk_id"] for chunk in chunks]
    if not reset:
        vectorstore.delete(ids=ids)
    vectorstore.add_documents(chunks, ids=ids)
    _stamp_embedding_model(vectorstore)
    return vectorstore


def _stamp_embedding_model(vectorstore: Chroma) -> None:
    metadata = dict(vectorstore._collection.metadata or {})
    metadata[_EMBEDDING_MODEL_KEY] = embedding_model_id()
    vectorstore._collection.modify(metadata=metadata)


def get_collection_stats(vectorstore: Chroma) -> dict[str, int]:
    return {"count": vectorstore._collection.count()}