---
type: service
id: dynamodb
name: Amazon DynamoDB
aliases: ["DynamoDB", "ddb", "dynamodb"]
depends_on: ["iam"]
owned_by: "TBD - set in review"
---

> Skeleton generated from the corpus inventory (`services:` frontmatter across
> `data/raw_rca_docs/`). The owning SRE must correct `owned_by`, `depends_on`,
> and the failure-mode list in PR review - curation is the point of this layer,
> the generator only guarantees the aliases actually seen in the corpus.


## What it is

Key-value store. Both failure modes here are access-pattern defects that only appear at production traffic shape, not in a load test with uniform keys.

## Known failure modes

- [Single partition key absorbing most of the write traffic](../failure-modes/hot-partition.md) - seen in INC-2025-0701
- [Query falling back to a full scan with no GSI to serve it](../failure-modes/missing-index.md) - seen in INC-2025-0702
