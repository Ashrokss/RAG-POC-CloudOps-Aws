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

`services` values are normalised to their canonical id from okf/services/*.md
at ingest, because the frontmatter is free text and the corpus was written by
several people: "lambda" and "Lambda" (5 docs each), "ec2"/"EC2",
"api-gateway"/"API Gateway", "ELB"/"ALB"/"alb". Any metadata filter on
services matched roughly half the documents it should have. An unrecognised
value is a warning naming the okf file that would fix it, never an exception -
the curated layer is expected to lag the corpus, and an ingest that refuses to
run until someone writes a concept file is an ingest nobody runs.
"""

from __future__ import annotations

import logging
from functools import lru_cache
from pathlib import Path

import frontmatter
from pydantic import ValidationError

from rag.models import RCADocumentMeta

logger = logging.getLogger(__name__)

# okf/ sits at the repo root, beside rag/ - resolved from __file__ rather than
# the process's cwd so ingest works from anywhere, and so the Azure App Service
# package (which copies rag/ and okf/ side by side) resolves it the same way.
_OKF_SERVICES_DIR = Path(__file__).resolve().parents[2] / "okf" / "services"

_warned_unknown_services: set[str] = set()

# The two source folders, defined here (beside the loader that walks them)
# because both rag/chain/rag_chain.py and rag/routing/incident_table.py need
# the same list and neither should own it.
CORPUS_DIRS = (Path("data/raw_rca_docs/real"), Path("data/raw_rca_docs/synthetic"))


def parse_frontmatter(text: str) -> tuple[dict, str]:
    metadata, body = frontmatter.parse(text)
    return metadata, body


@lru_cache(maxsize=1)
def service_alias_map() -> dict[str, str]:
    """lowercased alias -> canonical service id, built from okf/services/*.md."""
    mapping: dict[str, str] = {}
    for path in sorted(_OKF_SERVICES_DIR.glob("*.md")):
        metadata, _ = parse_frontmatter(path.read_text(encoding="utf-8"))
        service_id = str(metadata.get("id") or path.stem)
        aliases = metadata.get("aliases") or []
        for alias in [service_id, metadata.get("name", ""), *aliases]:
            if isinstance(alias, str) and alias.strip():
                mapping[alias.strip().lower()] = service_id
    return mapping


def canonical_service(name: str) -> str:
    """Canonical id for a free-text service name; the name unchanged (plus a
    one-time warning) when no okf/services file claims it."""
    canonical = service_alias_map().get(name.strip().lower())
    if canonical is not None:
        return canonical

    if name not in _warned_unknown_services:
        _warned_unknown_services.add(name)
        slug = name.strip().lower().replace(" ", "-")
        logger.warning(
            "Unknown service %r - no okf/services/*.md declares it as an id or "
            "alias, so it stays unnormalised and metadata filters will miss its "
            "spelling variants. Add it as an alias to an existing file, or write "
            "okf/services/%s.md.",
            name,
            slug,
        )
    return name


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

            services = metadata.get("services")
            if isinstance(services, list):
                metadata["services"] = [
                    canonical_service(service) if isinstance(service, str) else service
                    for service in services
                ]

            try:
                meta = RCADocumentMeta(**metadata)
            except ValidationError as exc:
                raise ValueError(f"Invalid RCA frontmatter in {path}: {exc}") from exc

            documents.append((meta, body))
    return documents