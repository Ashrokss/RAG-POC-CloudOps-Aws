---
type: failure-mode
id: iops-throttling
name: Provisioned IOPS ceiling saturated
services: ["ebs", "glue", "rds"]
incident_ids: ["INC-2025-0102"]
---

## What it is

gp3 storage's provisioned IOPS is a fixed, explicitly-set ceiling that does not scale with data volume the way storage-size autoscaling does; sustained write demand that grows past the provisioned baseline queues rather than completing, and nothing alarms on `WriteIOPS` utilization until the resulting queue depth is already high.

## Playbook

[Responding to a provisioned IOPS ceiling being saturated](../playbooks/iops-throttling.md)

## Seen in

- [INC-2025-0102](../../data/raw_rca_docs/synthetic/inc-2025-0102-rds-iops-throttling.md) - a nightly ETL's write volume grew 34% over two months due to a new table, pushing `WriteIOPS` to 100% of a 3,000-IOPS gp3 baseline; storage-size autoscaling (`MaxAllocatedStorage`) had no effect since it governs volume size, not IOPS, and the pipeline ran 3h12m over its window with two dependent Glue jobs timing out (see [timeout](timeout.md)).
