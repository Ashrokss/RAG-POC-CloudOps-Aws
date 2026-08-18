---
type: service
id: vpc
name: Amazon VPC
aliases: ["NAT Gateway", "VPC", "nat-gateway", "subnet", "vpc"]
depends_on: []
owned_by: "TBD - set in review"
---

> Skeleton generated from the corpus inventory (`services:` frontmatter across
> `data/raw_rca_docs/`). The owning SRE must correct `owned_by`, `depends_on`,
> and the failure-mode list in PR review - curation is the point of this layer,
> the generator only guarantees the aliases actually seen in the corpus.


## What it is

The network everything else sits in. Its failures are address-space and port-space arithmetic: a /26 subnet and a NAT gateway's per-destination port limit are both fixed ceilings that scale-out walks into.

## Known failure modes

- [Subnet IPv4 exhaustion starving ENI allocation](../failure-modes/quota-exhaustion.md) - seen in INC-2025-0201, INC-2025-0902
- [NAT gateway port exhaustion to a single destination](../failure-modes/port-exhaustion.md) - seen in INC-2025-1001
