---
type: service
id: ecr
name: Amazon ECR
aliases: ["ECR", "container-registry", "ecr"]
depends_on: ["iam"]
owned_by: "TBD - set in review"
---

> Skeleton generated from the corpus inventory (`services:` frontmatter across
> `data/raw_rca_docs/`). The owning SRE must correct `owned_by`, `depends_on`,
> and the failure-mode list in PR review - curation is the point of this layer,
> the generator only guarantees the aliases actually seen in the corpus.


## What it is

Container image registry behind the ECS services here. Present as the source of the image whose resource profile changed, not as a failing component itself.

## Known failure modes

- [New image shipping a changed memory profile](../failure-modes/config-regression.md) - seen in INC-2025-0901
