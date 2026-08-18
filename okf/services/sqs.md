---
type: service
id: sqs
name: Amazon SQS
aliases: ["SQS", "queue", "sqs"]
depends_on: ["lambda", "iam"]
owned_by: "TBD - set in review"
---

> Skeleton generated from the corpus inventory (`services:` frontmatter across
> `data/raw_rca_docs/`). The owning SRE must correct `owned_by`, `depends_on`,
> and the failure-mode list in PR review - curation is the point of this layer,
> the generator only guarantees the aliases actually seen in the corpus.


## What it is

Queueing between producers and consumers. Shows up as the place backlog becomes visible when a consumer is throttled, OOMing, or scanning.

## Known failure modes

- [Queue depth growing behind a throttled consumer](../failure-modes/backlog.md) - seen in INC-2025-0202
- [Queue depth growing behind an OOMing consumer](../failure-modes/backlog.md) - seen in INC-2025-0901
