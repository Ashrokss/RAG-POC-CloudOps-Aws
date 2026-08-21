---
type: service
id: alb
name: Elastic Load Balancing (ALB)
aliases: ["ALB", "Application Load Balancer", "ELB", "alb", "elb", "load-balancer"]
depends_on: ["vpc", "acm", "ec2", "ecs"]
owned_by: "TBD - set in review"
---

> Skeleton generated from the corpus inventory (`services:` frontmatter across
> `data/raw_rca_docs/`). The owning SRE must correct `owned_by`, `depends_on`,
> and the failure-mode list in PR review - curation is the point of this layer,
> the generator only guarantees the aliases actually seen in the corpus.


## What it is

Layer-7 load balancing in front of EC2 and ECS targets. Target-group health checks and deregistration delay are the two settings behind every ALB incident here.

## Known failure modes

- [Targets flapping in and out of the target group](../failure-modes/health-check-flapping.md) - seen in INC-2025-0802
- [Deregistration without draining in-flight requests](../failure-modes/connection-draining.md) - seen in INC-2025-0401
- [Listener certificate expiry](../failure-modes/cert-expiry.md) - seen in INC-2025-0801
