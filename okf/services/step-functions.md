---
type: service
id: step-functions
name: AWS Step Functions
aliases: ["Step Functions", "sfn", "step-functions", "stepfunctions"]
depends_on: ["lambda", "glue", "iam"]
owned_by: "TBD - set in review"
---

> Skeleton generated from the corpus inventory (`services:` frontmatter across
> `data/raw_rca_docs/`). The owning SRE must correct `owned_by`, `depends_on`,
> and the failure-mode list in PR review - curation is the point of this layer,
> the generator only guarantees the aliases actually seen in the corpus.


## What it is

Workflow orchestration for the batch pipelines here. Carries the retry and timeout policy that decides whether a slow downstream becomes a failed pipeline.

## Known failure modes

- [Pipeline overrunning its SLA window behind a throttled dependency](../failure-modes/timeout.md) - seen in INC-2025-0102
