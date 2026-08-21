"""
Canonical service ids from the curated concept layer.

Frontmatter `services` is free text written by several people, so one corpus
carried lambda/Lambda, ec2/EC2, api-gateway/"API Gateway", ELB/ALB/alb as
distinct values and any metadata filter matched roughly half of what it
should. Normalising at ingest is what makes a service filter - and therefore
the aggregate route - mean anything.

An unknown name is a warning naming the file that would fix it, never an
exception: the curated layer is expected to lag the corpus, and an ingest that
refuses to run until someone writes a concept file is an ingest nobody runs.
"""

from __future__ import annotations

import logging
from functools import lru_cache
from pathlib import Path

import frontmatter

logger = logging.getLogger(__name__)

VOCAB_DIR = Path(__file__).resolve().parents[1] / "knowledge" / "services"
_warned: set[str] = set()


@lru_cache(maxsize=1)
def alias_map() -> dict[str, str]:
    mapping: dict[str, str] = {}
    for path in sorted(VOCAB_DIR.glob("*.md")):
        meta, _ = frontmatter.parse(path.read_text(encoding="utf-8"))
        service_id = str(meta.get("id") or path.stem)
        for alias in [service_id, meta.get("name", ""), *(meta.get("aliases") or [])]:
            if isinstance(alias, str) and alias.strip():
                mapping[alias.strip().lower()] = service_id
    return mapping


def canonical(name: str) -> str:
    hit = alias_map().get(name.strip().lower())
    if hit:
        return hit
    if name not in _warned:
        _warned.add(name)
        logger.warning(
            "Unknown service %r - no knowledge/services/*.md claims it; it stays unnormalised "
            "and filters will miss its spelling variants. Add an alias, or write %s.md.",
            name,
            name.strip().lower().replace(" ", "-"),
        )
    return name


def canonical_all(names: list[str]) -> list[str]:
    return [canonical(n) for n in names]


def services_in(text: str) -> list[str]:
    """Canonical services named in free text, longest alias first so
    'API Gateway' wins over a bare 'api'."""
    import re

    lowered = text.lower()
    found: list[str] = []
    for alias, service_id in sorted(alias_map().items(), key=lambda kv: -len(kv[0])):
        if service_id in found:
            continue
        if re.search(rf"(?<![\w-]){re.escape(alias)}(?![\w-])", lowered):
            found.append(service_id)
    return found


def reset_cache() -> None:
    alias_map.cache_clear()
    _warned.clear()
