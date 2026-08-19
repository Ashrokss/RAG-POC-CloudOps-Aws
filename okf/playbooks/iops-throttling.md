---
type: playbook
id: iops-throttling
name: Responding to a provisioned IOPS ceiling being saturated
failure_mode: iops-throttling
services: ["ebs", "glue", "rds"]
owned_by: "TBD - set in review"
---

## When you see this

`DiskQueueDepth` alarms, `WriteIOPS` pinned at the provisioned ceiling, and/or read-replica lag climbing with no other explanation.

## Mitigate

1. Confirm via Performance Insights (or equivalent) that IOPS - not CPU, connections, or locking - is the dominant wait event.
2. Raise provisioned IOPS immediately; gp3 volumes support this without downtime or a storage-size change.
3. Re-run or reschedule any dependent job that failed on a timeout caused by the saturation, once IOPS heads back below the ceiling.

## Prevent

- Alarm on `WriteIOPS` utilization at ~80% of the provisioned baseline - a queue-depth alarm fires too late, only once the ceiling is already saturated.
- Re-baseline provisioned IOPS on a recurring schedule as write volume grows, rather than only after an incident forces a reactive increase.
- Document explicitly (in the runbook) that storage-size autoscaling governs volume size, not IOPS - the two are easy to conflate.

## Related

- Failure mode: [Provisioned IOPS ceiling saturated](../failure-modes/iops-throttling.md)
- Incidents: INC-2025-0102
