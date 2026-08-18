---
type: service
id: acm
name: AWS Certificate Manager
aliases: ["ACM", "Certificate Manager", "acm"]
depends_on: []
owned_by: "TBD - set in review"
---

> Skeleton generated from the corpus inventory (`services:` frontmatter across
> `data/raw_rca_docs/`). The owning SRE must correct `owned_by`, `depends_on`,
> and the failure-mode list in PR review - curation is the point of this layer,
> the generator only guarantees the aliases actually seen in the corpus.


## What it is

Certificate issue and renewal. Only appears in this corpus as an expiry that renewal automation did not cover - an imported certificate ACM never owned.

## Known failure modes

- [Imported certificate expiring outside managed renewal](../failure-modes/cert-expiry.md) - seen in INC-2025-0801
