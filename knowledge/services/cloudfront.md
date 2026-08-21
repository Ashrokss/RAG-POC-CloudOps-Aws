---
type: service
id: cloudfront
name: Amazon CloudFront
aliases: ["CDN", "CloudFront", "cdn", "cloudfront"]
depends_on: ["s3", "alb", "acm"]
owned_by: "TBD - set in review"
---

> Skeleton generated from the corpus inventory (`services:` frontmatter across
> `data/raw_rca_docs/`). The owning SRE must correct `owned_by`, `depends_on`,
> and the failure-mode list in PR review - curation is the point of this layer,
> the generator only guarantees the aliases actually seen in the corpus.


## What it is

CDN edge. Edge-visible 4xx/5xx in this corpus usually originate at the origin or its certificate, not at the edge itself - which is why an edge-error symptom needs origin-side retrieval to answer.

## Known failure modes

- [Origin/edge certificate expiring unrenewed](../failure-modes/cert-expiry.md) - seen in INC-2025-0801
- [Origin policy change surfacing as edge 4xx](../failure-modes/config-regression.md) - seen in INC-2025-0301
