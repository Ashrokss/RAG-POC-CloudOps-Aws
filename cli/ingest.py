"""
--source stays a bare str (not a Typer Enum) because the CLI contract here is
literally `source: str`; validity is checked once against the same two
folder names the loader already treats as the only two source directories,
so an invalid value fails fast with a clear message instead of silently
globbing zero files.

`stats` still resolves a real embedding_function (mock or Bedrock, whichever
mock_mode picks) before opening the collection even though counting never
embeds anything, because a Chroma handle is one embedding_function's view of
one collection - opening it with a mismatched one is the kind of mistake that
should be structurally impossible, not something stats() re-decides.
"""

from __future__ import annotations

from pathlib import Path

import typer

from config.settings import get_settings
from rag.embeddings.factory import get_embeddings
from rag.ingestion.chunker import chunk_all
from rag.ingestion.loader import load_rca_documents
from rag.vectorstore.chroma_store import build_index, get_collection_stats, get_vectorstore

app = typer.Typer()

_SOURCE_DIRS: dict[str, Path] = {
    "real": Path("data/raw_rca_docs/real"),
    "synthetic": Path("data/raw_rca_docs/synthetic"),
}


def _source_dirs(source: str) -> list[Path]:
    if source == "all":
        return list(_SOURCE_DIRS.values())
    if source in _SOURCE_DIRS:
        return [_SOURCE_DIRS[source]]
    raise typer.BadParameter(f"source must be one of real|synthetic|all, got {source!r}")


@app.command()
def run(
    reset: bool = typer.Option(False, "--reset", help="Drop and rebuild the collection instead of upserting."),
    source: str = typer.Option("all", "--source", help="Which corpus to ingest: real|synthetic|all."),
) -> None:
    settings = get_settings()
    docs = load_rca_documents(_source_dirs(source))
    chunks = chunk_all(docs, settings.chunk_size, settings.chunk_overlap)
    build_index(chunks, reset=reset)

    mode = "mock" if settings.mock_mode else "live"
    typer.echo(
        f"Ingested {len(docs)} doc(s) into {len(chunks)} chunk(s) "
        f"[source={source}, reset={reset}, mode={mode}]"
    )


@app.command()
def stats() -> None:
    settings = get_settings()
    vectorstore = get_vectorstore(get_embeddings())
    collection_stats = get_collection_stats(vectorstore)

    mode = "mock" if settings.mock_mode else "live"
    typer.echo(
        f"Collection '{settings.chroma_collection_name}': {collection_stats['count']} chunk(s) [mode={mode}]"
    )


if __name__ == "__main__":
    app()