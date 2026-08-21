---
type: service
id: ec2
name: Amazon EC2
aliases: ["Auto Scaling", "EC2", "asg", "auto-scaling", "ec2"]
depends_on: ["vpc", "iam", "ebs"]
owned_by: "TBD - set in review"
---

> Skeleton generated from the corpus inventory (`services:` frontmatter across
> `data/raw_rca_docs/`). The owning SRE must correct `owned_by`, `depends_on`,
> and the failure-mode list in PR review - curation is the point of this layer,
> the generator only guarantees the aliases actually seen in the corpus.


## What it is

Instance compute, including the Auto Scaling groups that front it. Failures here are usually the scaling loop reacting to a health signal that does not mean what the ASG thinks it means.

## Known failure modes

- [ASG replacing healthy instances on a mis-scoped health check](../failure-modes/health-check-flapping.md) - seen in INC-2025-0402
- [Instances terminated without draining in-flight requests](../failure-modes/connection-draining.md) - seen in INC-2025-0401
- [Subnet IP / NAT port exhaustion under scale-out](../failure-modes/quota-exhaustion.md) - seen in INC-2025-1001
