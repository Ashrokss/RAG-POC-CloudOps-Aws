---
type: service
id: route-53
name: Amazon Route 53
aliases: ["Route 53", "Route53", "route-53", "route53"]
depends_on: ["alb", "cloudfront"]
owned_by: "TBD - set in review"
---

> Skeleton generated from the corpus inventory (`services:` frontmatter across
> `data/raw_rca_docs/`). The owning SRE must correct `owned_by`, `depends_on`,
> and the failure-mode list in PR review - curation is the point of this layer,
> the generator only guarantees the aliases actually seen in the corpus.


## What it is

DNS and health checking. In this corpus it is the detector rather than the failure - its HTTPS health check was the first signal of the certificate expiry.

## Known failure modes

- [Health check failing on an expired origin certificate](../failure-modes/cert-expiry.md) - seen in INC-2025-0801
