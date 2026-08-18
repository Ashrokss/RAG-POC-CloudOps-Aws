---
type: service
id: lambda
name: AWS Lambda
aliases: ["AWS Lambda", "Lambda", "aws-lambda", "lambda"]
depends_on: ["vpc", "iam"]
owned_by: "TBD - set in review"
---

> Skeleton generated from the corpus inventory (`services:` frontmatter across
> `data/raw_rca_docs/`). The owning SRE must correct `owned_by`, `depends_on`,
> and the failure-mode list in PR review - curation is the point of this layer,
> the generator only guarantees the aliases actually seen in the corpus.


## What it is

Serverless compute. Every function in this corpus runs behind either API Gateway or an event source (SQS, EventBridge), and the VPC-attached ones draw an ENI per concurrent execution - which is why its failures show up as networking and quota failures at least as often as code failures.

## Known failure modes

- [ENI exhaustion in a VPC-attached function](../failure-modes/quota-exhaustion.md) - seen in INC-2025-0201, INC-2025-0902
- [Reserved-concurrency ceiling rejecting a legitimate spike](../failure-modes/throttling.md) - seen in INC-2025-0202
- [Downstream integration exceeding the caller's timeout](../failure-modes/timeout.md) - seen in INC-2025-0602
- [Unpooled database connections scaling with concurrency](../failure-modes/connection-pool-exhaustion.md) - seen in INC-2025-0101
