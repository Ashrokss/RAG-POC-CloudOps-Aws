---
type: service
id: ebs
name: Amazon EBS
aliases: ["EBS", "block-storage", "ebs"]
depends_on: ["ec2"]
owned_by: "TBD - set in review"
---

> Skeleton generated from the corpus inventory (`services:` frontmatter across
> `data/raw_rca_docs/`). The owning SRE must correct `owned_by`, `depends_on`,
> and the failure-mode list in PR review - curation is the point of this layer,
> the generator only guarantees the aliases actually seen in the corpus.


## What it is

Block storage for EC2 and RDS. Its ceilings are IOPS and throughput, which is where the database incidents in this corpus actually bind.

## Known failure modes

- [Provisioned IOPS ceiling throttling writes](../failure-modes/iops-throttling.md) - seen in INC-2025-0102
- [Volume operations degraded by a dependent service outage](../failure-modes/regional-outage.md) - seen in INC-2017-0228-S3-USEAST1
