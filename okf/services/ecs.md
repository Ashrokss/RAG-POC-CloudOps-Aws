---
type: service
id: ecs
name: Amazon ECS
aliases: ["ECS", "Fargate", "ecs", "fargate"]
depends_on: ["vpc", "iam", "alb", "ecr"]
owned_by: "TBD - set in review"
---

> Skeleton generated from the corpus inventory (`services:` frontmatter across
> `data/raw_rca_docs/`). The owning SRE must correct `owned_by`, `depends_on`,
> and the failure-mode list in PR review - curation is the point of this layer,
> the generator only guarantees the aliases actually seen in the corpus.


## What it is

Container orchestration, Fargate and EC2 launch types both. Task-level resource limits and the ENI-per-task model are where this shows up in incidents.

## Known failure modes

- [Task OOMKilled against a memory limit set below real usage](../failure-modes/oom.md) - seen in INC-2025-0901
- [ENI exhaustion across tasks in one subnet](../failure-modes/quota-exhaustion.md) - seen in INC-2025-0902
- [Target group flapping tasks in and out of service](../failure-modes/health-check-flapping.md) - seen in INC-2025-0802
