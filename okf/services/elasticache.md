---
type: service
id: elasticache
name: Amazon ElastiCache
aliases: ["ElastiCache", "ElastiCache for Redis", "Redis", "elasticache", "redis"]
depends_on: ["vpc"]
owned_by: "TBD - set in review"
---

> Skeleton generated from the corpus inventory (`services:` frontmatter across
> `data/raw_rca_docs/`). The owning SRE must correct `owned_by`, `depends_on`,
> and the failure-mode list in PR review - curation is the point of this layer,
> the generator only guarantees the aliases actually seen in the corpus.


## What it is

Managed Redis. The two incidents here failed on opposite sides of the boundary - one server-side eviction policy, one client-side failover handling - which makes this the cleanest pair in the corpus for testing whether retrieval distinguishes similar-sounding incidents.

## Known failure modes

- [Eviction storm under an unsuitable maxmemory-policy](../failure-modes/eviction.md) - seen in INC-2025-0501
- [Client not re-resolving the primary endpoint after failover](../failure-modes/failover.md) - seen in INC-2025-0502
