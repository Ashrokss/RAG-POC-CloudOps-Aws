---
type: service
id: rds
name: Amazon RDS
aliases: ["PostgreSQL", "RDS", "postgres", "postgresql", "rds"]
depends_on: ["vpc", "ebs"]
owned_by: "TBD - set in review"
---

> Skeleton generated from the corpus inventory (`services:` frontmatter across
> `data/raw_rca_docs/`). The owning SRE must correct `owned_by`, `depends_on`,
> and the failure-mode list in PR review - curation is the point of this layer,
> the generator only guarantees the aliases actually seen in the corpus.


## What it is

Managed relational databases. Both incidents are capacity limits reached by something upstream that had no matching limit of its own.

## Known failure modes

- [Connection demand exceeding max_connections](../failure-modes/connection-pool-exhaustion.md) - seen in INC-2025-0101
- [Provisioned IOPS ceiling throttling writes](../failure-modes/iops-throttling.md) - seen in INC-2025-0102
