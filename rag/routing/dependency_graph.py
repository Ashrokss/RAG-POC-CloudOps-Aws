"""
okf/services/*.md's depends_on field is forward ("this service depends on
these") and direct-only. A blast-radius question asks the reverse and
transitive question - "what depends on this, at any distance" - so this
module inverts the graph once and walks it breadth-first, rather than
re-deriving either direction from service_dependency_graph() on every call.

Cycle-safety is defensive, not load-bearing: the 21-service graph is
curated by hand and is a DAG in practice (foundational services like vpc/iam
have empty depends_on), but downstream_of() tracks visited ids regardless so
a future curation mistake degrades to a wrong-but-terminating answer instead
of an infinite loop.
"""

from __future__ import annotations

from functools import lru_cache

from rag.ingestion.loader import service_dependency_graph


@lru_cache(maxsize=1)
def _reverse_graph() -> dict[str, list[str]]:
    """canonical service id -> ids of services that name it directly in
    their own depends_on - i.e. what would be affected first if it failed."""
    forward = service_dependency_graph()
    reverse: dict[str, list[str]] = {service_id: [] for service_id in forward}
    for service_id, deps in forward.items():
        for dep in deps:
            reverse.setdefault(dep, []).append(service_id)
    return reverse


def reset_dependency_graph() -> None:
    service_dependency_graph.cache_clear()
    _reverse_graph.cache_clear()


def downstream_of(service_id: str) -> list[str]:
    """Every service that depends on service_id, directly or transitively,
    ordered nearest-first. Empty if service_id is unknown or nothing in the
    curated graph names it - a real answer, not an error: the graph is
    expected to lag which services actually exist (see canonical_service)."""
    reverse = _reverse_graph()
    visited = {service_id}
    ordered: list[str] = []
    frontier = list(reverse.get(service_id, []))
    while frontier:
        next_frontier: list[str] = []
        for dependent in frontier:
            if dependent in visited:
                continue
            visited.add(dependent)
            ordered.append(dependent)
            next_frontier.extend(reverse.get(dependent, []))
        frontier = next_frontier
    return ordered


def render_impact(impact: dict[str, list[str]]) -> str:
    """One line per origin service - the id and everything downstream of it,
    per downstream_of(). 'none recorded' (not 'none') because an empty result
    means the curated graph has no dependents on file, not that none exist."""
    lines = []
    for service_id, downstream in impact.items():
        rendered = ", ".join(downstream) if downstream else "none recorded"
        lines.append(f"{service_id} -> depended on by (directly or transitively): {rendered}")
    return "\n".join(lines)
