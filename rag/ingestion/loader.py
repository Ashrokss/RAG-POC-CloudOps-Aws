"""
python-frontmatter (not a hand-rolled '---' split) owns frontmatter parsing
because YAML values routinely contain colons, quotes, and nested lists
(services, tags) that a naive string split would mangle.

Directories are walked non-recursively and by design: `data/raw_rca_docs/`
holds `real/` and `synthetic/` as the only two source folders, each flat, so
recursion would just risk silently pulling in whatever else ends up nested
under them.

A file that fails to parse or validate raises immediately instead of being
skipped - a bad RCA doc silently dropped from the corpus fails the eval
harness in a way that looks like a retrieval bug, not an ingestion one.
"""

from __future__ import annotations

from pathlib import Path

import frontmatter
from pydantic import ValidationError

from rag.models import RCADocumentMeta


def parse_frontmatter(text: str) -> tuple[dict, str]:
    metadata, body = frontmatter.parse(text)
    return metadata, body


def load_rca_documents(root_dirs: list[Path]) -> list[tuple[RCADocumentMeta, str]]:
    documents: list[tuple[RCADocumentMeta, str]] = []
    for root_dir in root_dirs:
        for path in sorted(root_dir.glob("*.md")):
            if path.name.lower() == "readme.md" or path.name.startswith("_"):
                continue

            metadata, body = parse_frontmatter(path.read_text(encoding="utf-8"))
            # An explicitly blank doc_id (the template's documented way of asking
            # ingestion to generate one) must not shadow RCADocumentMeta's
            # default_factory by passing "" through as the literal id.
            if not metadata.get("doc_id"):
                metadata.pop("doc_id", None)

            try:
                meta = RCADocumentMeta(**metadata)
            except ValidationError as exc:
                raise ValueError(f"Invalid RCA frontmatter in {path}: {exc}") from exc

            documents.append((meta, body))
    return documents