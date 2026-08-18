---
doc_id: "fca24f95-19cb-4418-908f-2b49974a6f9f"
incident_id: "INC-2025-0701"
title: "DynamoDB Hot Partition Throttling During Tenant Batch Import"
date: "2025-07-08T02:14:00Z"
severity: high
services: ["DynamoDB", "Lambda", "SQS"]
region: "eu-west-1"
account_id: "904261738850"
status: "resolved"
tags: ["dynamodb", "hot-partition", "throttling", "batch-import", "sqs-dlq"]
source: synthetic
# Extracted by hand from this document's own Impact and Detection sections
# so aggregate questions (longest detection gap, total cost, duration
# ranking) can be answered by sorting a column instead of hoping top-k
# retrieval happens to surface every relevant doc. null = not stated above.
detection_gap_minutes: 14
duration_minutes: 220
cost_usd: null
---

## Summary

A batch import of 2.4 million historical event records for one enterprise tenant
(`tenant_00042`) into `customer-events-prod` overwhelmed a single physical partition because
every item shared the same partition key value (`tenant_id`). Despite 4,000 WCU of table-level
provisioned throughput, DynamoDB's hard per-partition ceiling of 1,000 WCU cannot be exceeded
regardless of table capacity, and `BatchWriteItem` calls were rejected with
`ProvisionedThroughputExceededException` for 3 hours 40 minutes. 612,000 records were routed to
the dead-letter queue, and other tenants sharing the table saw write latency degrade while
adaptive capacity rebalanced.

## Timeline

- 2025-07-08T02:00:00Z - EventBridge rule `nightly-tenant-batch-import` triggers Lambda
  `batch-event-importer` to load 2.4M records (all `tenant_id = tenant_00042`) into
  `customer-events-prod`.
- 2025-07-08T02:11:30Z - Importer ramps to a sustained ~9,200 WCU demand against the single
  `tenant_00042` partition.
- 2025-07-08T02:14:00Z - CloudWatch alarm `customer-events-prod-write-throttle` (metric
  `ThrottledWriteRequests` > 100 for 5 minutes) fires; on-call SRE paged.
- 2025-07-08T02:19:45Z - On-call confirms `ProvisionedThroughputExceededException: The level of
  configured provisioned throughput for the table was exceeded. Consider increasing your
  provisioning level with the UpdateTable API.` on most `BatchWriteItem` calls, while
  `ConsumedWriteCapacityUnits` stays well under the 4,000 WCU provisioned.
- 2025-07-08T02:27:10Z - All throttled requests are confirmed to share partition key `tenant_id =
  tenant_00042`, pointing to the 1,000 WCU per-partition ceiling rather than table capacity.
- 2025-07-08T02:35:00Z - Failed batches accumulate in SQS DLQ `batch-event-importer-dlq`; 612,000
  records eventually land there.
- 2025-07-08T03:05:00Z - On-call disables the `nightly-tenant-batch-import` rule to stop further
  write pressure while a fix is designed.
- 2025-07-08T05:54:00Z - Redesigned importer, writing with a sharded key (`tenant_id#shard`, 10
  shards hashed from `event_id`) and capped at 5 concurrent invocations via an SQS FIFO queue, is
  re-run successfully with zero throttling.

## Root Cause

`customer-events-prod` uses `tenant_id` as its sole partition key. `tenant_00042` is an outsized
tenant whose import (100% under one key) far exceeded what a single physical partition can serve.
DynamoDB enforces a per-partition ceiling of 3,000 RCU / 1,000 WCU independent of overall table
capacity; adaptive capacity can shift heat toward a busy partition over time but could not absorb
a sustained ~9,200 WCU demand against one key, and its burst was exhausted within the first two
minutes. The trigger was the scheduled import; the root cause is a partition key design with no
mechanism to spread one tenant's high-volume write burst across multiple physical partitions.

## Impact

- Import failed and retried for 3 hours 40 minutes before being paused.
- 612,000 of 2.4M records routed to `batch-event-importer-dlq`.
- `tenant_00042`'s dashboard showed data staleness up to 4 hours.
- Other tenants saw p99 write latency rise from 12 ms to 340 ms for ~25 minutes during
  rebalancing.
- No permanent data loss - all DLQ'd records were successfully reprocessed after the fix.

## Detection

CloudWatch alarm `customer-events-prod-write-throttle` (`ThrottledWriteRequests` > 100 for 5
minutes) paged on-call 14 minutes after the import started; a secondary alarm on
`batch-event-importer` error rate corroborated the finding shortly after.

## Resolution

1. Confirmed throttling was isolated to partition key `tenant_00042`, not overall table capacity.
2. Disabled the `nightly-tenant-batch-import` rule to halt write pressure.
3. Redesigned the importer to write-shard as `tenant_id#shard` (10 shards, hashed from
   `event_id`), spreading writes across 10 logical partitions.
4. Capped importer concurrency to 5 invocations via an SQS FIFO queue with 5 message groups, and
   added exponential backoff with jitter around retries.
5. Re-ran the import with zero throttling, then reprocessed the 612,000 DLQ'd records the same
   way.

## Action Items

1. Apply the write-sharded key pattern to all bulk-import paths writing to
   `customer-events-prod`. Owner: Data Platform team. Ticket: JIRA-6301.
2. Add a pre-import validation step estimating projected WCU demand per partition key against the
   1,000 WCU ceiling. Owner: Data Platform team. Ticket: JIRA-6302.
3. Lower the `ThrottledWriteRequests` alarm threshold from >100 to >20 over 5 minutes for earlier
   detection. Owner: SRE team. Ticket: JIRA-6303.
4. Evaluate migrating to on-demand capacity mode for scheduled bulk-load windows; reassess after
   one quarter of cost data. Owner: SRE team. Ticket: JIRA-6304.
