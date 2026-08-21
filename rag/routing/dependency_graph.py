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

import re
from functools import lru_cache

from rag.ingestion.loader import service_alias_map, service_dependency_graph

_IMPACT_LINE_RE = re.compile(
    r"^(?P<origin>[\w-]+) -> depended on by \(directly or transitively\): (?P<downstream>.+)$",
    re.MULTILINE,
)


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


def check_dependency_completeness(answer: str, index_block: str) -> list[dict]:
    """Downstream service ids render_impact() named that never appear (by
    canonical id, display name, or any okf/services/*.md alias) anywhere in
    the answer's prose.

    Lives here, not in eval/, because rag/chain/rag_chain.py's generate()
    uses it directly to decide whether to retry a live answer, not only to
    score one after the fact - a live spot-check found the model handed all
    four of ACM's downstream services but narrated only the two also named
    in a retrieved incident excerpt, silently dropping the two transitive
    ones that had no supporting text. A token-overlap or grounding check
    (eval/grounding.py) cannot see this: the answer stated nothing false, it
    omitted true, structurally-given facts - so this checks presence, not
    accuracy.

    Deliberately lenient on matching: 'ecs' passes if the answer says 'ECS',
    'Amazon ECS', or any alias okf/services/ecs.md declares, not just the
    bare canonical id."""
    if "### DEPENDENCY IMPACT ###" not in index_block:
        return []

    aliases_by_id: dict[str, list[str]] = {}
    for alias, service_id in service_alias_map().items():
        aliases_by_id.setdefault(service_id, []).append(alias)

    violations: list[dict] = []
    for line_match in _IMPACT_LINE_RE.finditer(index_block):
        origin = line_match.group("origin")
        downstream_ids = [
            entry.strip()
            for entry in line_match.group("downstream").split(",")
            if entry.strip() and entry.strip() != "none recorded"
        ]
        for service_id in downstream_ids:
            candidates = aliases_by_id.get(service_id, [service_id])
            named = any(
                re.search(rf"(?<![\w-]){re.escape(alias)}(?![\w-])", answer, re.IGNORECASE)
                for alias in candidates
            )
            if not named:
                violations.append({"origin": origin, "missing_service": service_id})
    return violations
