---
type: service
id: glue
name: AWS Glue
aliases: ["Glue", "glue"]
depends_on: ["rds", "s3", "iam"]
owned_by: "TBD - set in review"
---

> Skeleton generated from the corpus inventory (`services:` frontmatter across
> `data/raw_rca_docs/`). The owning SRE must correct `owned_by`, `depends_on`,
> and the failure-mode list in PR review - curation is the point of this layer,
> the generator only guarantees the aliases actually seen in the corpus.


## What it is

Managed ETL. Appears as the workload whose write volume saturated the database it loaded into, and as the job that failed and needed manual rerun.

## Known failure modes

- [ETL write volume saturating the target's IOPS ceiling](../failure-modes/iops-throttling.md) - seen in INC-2025-0102
