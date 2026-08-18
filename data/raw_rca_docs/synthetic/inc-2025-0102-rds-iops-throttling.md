---
doc_id: "f8c8d772-7708-4a36-aeb6-8ec48c00cc52"
incident_id: "INC-2025-0102"
title: "RDS Storage Autoscaling Threshold Too High, Causing IOPS Throttling During Nightly ETL"
date: "2025-03-04T02:15:00Z"
severity: high
services: ["rds", "glue", "step-functions"]
region: "us-west-2"
account_id: "418773529104"
status: "resolved"
tags: ["rds", "iops", "storage-autoscaling", "etl", "mysql"]
source: synthetic
# Extracted by hand from this document's own Impact and Detection sections
# so aggregate questions (longest detection gap, total cost, duration
# ranking) can be answered by sorting a column instead of hoping top-k
# retrieval happens to surface every relevant doc. null = not stated above.
detection_gap_minutes: 52
duration_minutes: 192
cost_usd: null
---

## Summary

The nightly ETL pipeline loading the previous day's transactional data into `analytics-prod-mysql`
(RDS MySQL, db.r6g.4xlarge, gp3 storage, provisioned 3,000 IOPS) ran 3 hours 12 minutes over its
normal 90-minute window on March 4, 2025, and two dependent AWS Glue jobs failed with timeout
errors. Data growth from a new event-tracking table had pushed the ETL job's write volume well
past what the 3,000-IOPS baseline was sized for, and because gp3 storage-size autoscaling
(`MaxAllocatedStorage`) governs volume capacity, not IOPS, nothing scaled to compensate.
`WriteIOPS` sustained at 100% of the provisioned baseline, throttling every subsequent write and
cascading into read-replica lag that peaked at 41 minutes.

## Timeline

- 2025-03-04T02:00:00Z - Nightly ETL Step Functions state machine `etl-daily-load-prod` begins,
  triggering bulk `INSERT ... ON DUPLICATE KEY UPDATE` batches against `analytics-prod-mysql`.
- 2025-03-04T02:41:00Z - `WriteIOPS` sustains at 2,950-3,010, effectively 100% of the provisioned
  3,000 IOPS baseline.
- 2025-03-04T02:52:00Z - CloudWatch alarm `analytics-prod-mysql-DiskQueueDepth-High` fires as
  `DiskQueueDepth` exceeds 64 for 5 consecutive minutes.
- 2025-03-04T03:05:00Z - Read replica `analytics-prod-mysql-replica-1` reports `ReplicaLag` of 22
  minutes and climbing; downstream dashboards show stale data.
- 2025-03-04T03:10:00Z - On-call SRE paged; acknowledges in 4 minutes. RDS Performance Insights
  shows top wait event `IO: XactSync` at 78% of DB load.
- 2025-03-04T03:28:00Z - Glue job `glue-job-daily-aggregate` fails with
  `java.sql.SQLTimeoutException: Statement cancelled due to timeout or client request` after
  exceeding its 30-minute timeout.
- 2025-03-04T03:41:00Z - Replication lag peaks at 41 minutes.
- 2025-03-04T03:55:00Z - Mitigation: on-call increases provisioned IOPS from 3,000 to 8,000 via
  `aws rds modify-db-instance --db-instance-identifier analytics-prod-mysql --iops 8000
  --apply-immediately`.
- 2025-03-04T04:20:00Z - `WriteIOPS` utilization drops to 61%; `DiskQueueDepth` falls below 10.
- 2025-03-04T05:12:00Z - ETL pipeline completes; replication lag returns to under 5 seconds.
  Incident resolved.

## Root Cause

`analytics-prod-mysql` used gp3 storage provisioned at 3,000 IOPS, sized for daytime OLTP traffic
averaging ~900 IOPS. The nightly ETL's write pattern - large batched upserts with secondary index
maintenance - is far more IOPS-intensive, historically peaking around 2,400 IOPS, within tolerance
until data volume grew 34% over the preceding two months due to a new event-tracking table,
`user_activity_events`, causing the same ETL logic to generate proportionally more index writes
per run. `MaxAllocatedStorage` autoscaling was configured on the instance, but it grows volume
size when free space drops low - it does not add IOPS headroom, since gp3 IOPS must be provisioned
explicitly and does not scale with data volume. With no alarm on `WriteIOPS` relative to the
provisioned baseline, the growing write load silently sustained at 100% of the 3,000 IOPS ceiling
before anyone was alerted, at which point every additional write queued rather than completing.

## Impact

- Nightly ETL pipeline overran its SLA window by 3 hours 12 minutes (normal ~90 min, actual 5h12m).
- Two Glue jobs (`glue-job-daily-aggregate`, `glue-job-daily-fraud-scoring`) failed and required
  manual reruns, delaying the 6:00 AM PT executive revenue dashboard by 4 hours.
- Replica lag peaked at 41 minutes, showing the customer-facing "Order History" page (served from
  the replica) up to 41 minutes stale for an estimated 6,200 users.
- No customer-facing 5xx errors; impact was data freshness and internal-reporting latency only.

## Detection

Detected via CloudWatch alarm `analytics-prod-mysql-DiskQueueDepth-High`, triggering when
`DiskQueueDepth` exceeds 64 for 5 consecutive 1-minute periods. It fired 52 minutes after the ETL
job started, roughly 11 minutes after `WriteIOPS` first sustained at its ceiling - queue depth
only builds up once the IOPS ceiling is already saturated, so this alarm structurally cannot give
early warning.

## Resolution

1. On-call reviewed Performance Insights, identified `IO: XactSync` as the dominant wait event,
   and confirmed `WriteIOPS` pinned at the provisioned 3,000 ceiling.
2. Applied an immediate provisioned-IOPS increase to 8,000 via `modify-db-instance
   --apply-immediately`, which for gp3 volumes applies without downtime or a storage-size change.
3. Manually re-ran both failed Glue jobs once ETL completed.
4. Verified replication lag returned to baseline before closing the incident.

## Action Items

- Add a CloudWatch alarm on `WriteIOPS` reaching 80% of provisioned IOPS, evaluated over 5-minute
  windows, to catch saturation before queue depth builds up. Owner: Data Platform SRE. Ticket:
  SRE-5102.
- Re-baseline provisioned IOPS to 6,000 permanently for `user_activity_events` growth, with a
  quarterly review of ETL IOPS consumption. Owner: Data Platform SRE. Ticket: SRE-5103.
- Document in the RDS runbook that `MaxAllocatedStorage` governs volume size, not IOPS, to prevent
  this misunderstanding recurring. Owner: SRE team. Ticket: SRE-5104.
- Split nightly ETL upsert batches into smaller chunks with brief pauses to smooth peak IOPS
  demand. Owner: Data Engineering team. Ticket: SRE-5105.
