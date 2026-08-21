---
type: service
id: iam
name: AWS IAM
aliases: ["IAM", "STS", "iam", "sts"]
depends_on: []
owned_by: "TBD - set in review"
---

> Skeleton generated from the corpus inventory (`services:` frontmatter across
> `data/raw_rca_docs/`). The owning SRE must correct `owned_by`, `depends_on`,
> and the failure-mode list in PR review - curation is the point of this layer,
> the generator only guarantees the aliases actually seen in the corpus.


## What it is

Identity and access. Every IAM incident in this corpus is a change that was correct in isolation and wrong in combination with a caller nobody re-tested.

## Known failure modes

- [Trust policy change breaking an assuming principal](../failure-modes/config-regression.md) - seen in INC-2025-1002
- [Resource policy change denying a legitimate caller](../failure-modes/config-regression.md) - seen in INC-2025-0301
