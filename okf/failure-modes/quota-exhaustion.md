---
type: failure-mode
id: quota-exhaustion
name: Subnet IP / ENI capacity exhausted under scale-out
services: ["ec2", "ecs", "lambda", "vpc"]
incident_ids: ["INC-2025-0201", "INC-2025-0902", "INC-2025-1001"]
---

## What it is

VPC-attached compute (Lambda, ECS Fargate tasks) draws from a fixed pool of subnet IP addresses, one ENI per execution environment. A subnet sized for the service count and scale that existed when it was provisioned can run out of that pool during a later scale-out event, with no warning beforehand because nothing alerted on shrinking headroom as usage grew.

## Seen in

- [INC-2025-0201](../../data/raw_rca_docs/synthetic/inc-2025-0201-lambda-eni-exhaustion.md) - a /26 subnet (59 usable IPs) shared by four VPC-attached Lambda functions and several EC2 batch workers ran out of free addresses when three new functions were deployed into it during a traffic burst; new invocations either queued behind slow ENI reuse (18.4s p99 cold starts) or failed with `EniLimitExceededException`.
- [INC-2025-0902](../../data/raw_rca_docs/synthetic/inc-2025-0902-ecs-eni-exhaustion.md) - two /26 production subnets shared by three ECS services had only ~23 free IPs combined when Application Auto Scaling tried to add 120 Fargate tasks for a flash sale; most task placements failed at ENI creation, capping real capacity at 52-70 of a 160-task target.
- [INC-2025-1001](../../data/raw_rca_docs/synthetic/inc-2025-1001-natgw-port-exhaustion.md) - scaling a payment-worker ASG from 40 to 260 instances concentrated outbound connections through a single NAT Gateway onto a small, fixed set of upstream IPs, exceeding the gateway's own per-destination connection ceiling (see [port-exhaustion](port-exhaustion.md)).
