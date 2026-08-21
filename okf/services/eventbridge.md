---
type: service
id: eventbridge
name: Amazon EventBridge
aliases: ["EventBridge", "cloudwatch-events", "event-bridge", "eventbridge"]
depends_on: ["lambda", "iam"]
owned_by: "TBD - set in review"
---

> Skeleton generated from the corpus inventory (`services:` frontmatter across
> `data/raw_rca_docs/`). The owning SRE must correct `owned_by`, `depends_on`,
> and the failure-mode list in PR review - curation is the point of this layer,
> the generator only guarantees the aliases actually seen in the corpus.


## What it is

Event routing between services. Appears in this corpus as the trigger path for scheduled and reactive Lambda work rather than as the failing component itself.

## Known failure modes

- [Rule target failing after an IAM trust change](../failure-modes/config-regression.md) - seen in INC-2025-1002
- [Downstream target unable to keep up with rule fan-out](../failure-modes/throttling.md) - seen in INC-2025-0702
