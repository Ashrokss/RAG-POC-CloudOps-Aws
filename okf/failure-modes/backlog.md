---
type: failure-mode
id: backlog
name: Queue growing behind an impaired consumer
services: ["sqs"]
incident_ids: ["INC-2025-0202", "INC-2025-0901"]
---

## What it is

A queue's depth grows unbounded when its consumer is impaired - throttled below the ceiling it needs, or crash-looping - rather than because producers sent an unusual volume; the backlog itself becomes a second problem (delayed processing, dead-letter growth) on top of whatever impaired the consumer.

## Playbook

[Responding to a queue backing up behind an impaired consumer](../playbooks/backlog.md)

## Seen in

- [INC-2025-0202](../../data/raw_rca_docs/synthetic/inc-2025-0202-lambda-concurrency-throttling.md) - a Lambda consumer's fixed reserved-concurrency ceiling throttled it below incoming volume during a launch spike (see [throttling](throttling.md)), backing up `notification-dispatch-queue` to 214,300 messages and sending 312 past their retry limit to the DLQ.
- [INC-2025-0901](../../data/raw_rca_docs/synthetic/inc-2025-0901-ecs-oomkilled.md) - an ECS consumer cycling through OOM kills every 5-9 minutes (see [oom](oom.md)) couldn't keep pace with `metrics-ingest-queue`, which grew to 1.2 million messages before the rollback restored steady consumption.
