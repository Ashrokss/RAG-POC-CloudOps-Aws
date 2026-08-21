---
type: service
id: api-gateway
name: Amazon API Gateway
aliases: ["API Gateway", "api-gateway", "apigateway", "apigw"]
depends_on: ["lambda", "iam"]
owned_by: "TBD - set in review"
---

> Skeleton generated from the corpus inventory (`services:` frontmatter across
> `data/raw_rca_docs/`). The owning SRE must correct `owned_by`, `depends_on`,
> and the failure-mode list in PR review - curation is the point of this layer,
> the generator only guarantees the aliases actually seen in the corpus.


## What it is

The HTTP front door for most Lambda-backed services in this corpus. Its account-level burst limits and its fixed integration timeout are both hard edges that the backing function's own limits do not see.

## Known failure modes

- [Account burst limit rejecting a launch spike](../failure-modes/throttling.md) - seen in INC-2025-0601
- [Integration timeout firing before the backend finishes](../failure-modes/timeout.md) - seen in INC-2025-0602
