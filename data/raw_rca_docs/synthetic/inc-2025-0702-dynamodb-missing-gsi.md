---
doc_id: "1d1168e0-5a88-4c52-ad00-03bec93ebd87"
incident_id: "INC-2025-0702"
title: "DynamoDB Full Table Scans from Missing GSI Drive Latency and Cost Spike"
date: "2025-07-22T09:00:00Z"
severity: medium
services: ["DynamoDB", "Lambda", "EventBridge"]
region: "us-east-1"
account_id: "611349207823"
status: "resolved"
tags: ["dynamodb", "gsi", "scan", "cost-spike", "latency"]
source: synthetic
# Extracted by hand from this document's own Impact and Detection sections
# so aggregate questions (longest detection gap, total cost, duration
# ranking) can be answered by sorting a column instead of hoping top-k
# retrieval happens to surface every relevant doc. null = not stated above.
detection_gap_minutes: null
duration_minutes: 12960
cost_usd: 20700
---

## Summary

Two code paths against the 42.6 million-item `orders-prod` table - a support-lookup Lambda and a
nightly reconciliation job - used `Scan` with `FilterExpression` on `customer_email` and `status`
because no GSI existed for either access pattern. An EventBridge schedule bug
(`rate(15 minutes)` instead of the intended `rate(1 day)`) multiplied the frequency of these
scans roughly 96x, driving auto scaling to repeatedly raise `orders-prod`'s provisioned read
capacity toward its 20,000 RCU ceiling while checkout's read path, sharing the table, saw p99
latency rise from 8 ms to 1,850 ms. DynamoDB spend for the table rose from ~$640/day to
$2,940/day for 9 days before the cause was traced.

## Timeline

- 2025-07-13T00:00:00Z - PR #4471 ships order lookup by email and reconciliation job
  `orders-pending-reconciliation-job` (flags `status = PENDING_REVIEW`); both use `Scan` since no
  supporting index exists. The reconciliation job's EventBridge rule is misconfigured as
  `rate(15 minutes)` instead of `rate(1 day)`.
- 2025-07-13T00:15:00Z through 2025-07-21T - The job runs every 15 minutes, each execution
  scanning all 42.6M items (~31 GB) and consuming ~118,000 RCU over ~90 seconds.
- 2025-07-21T - AWS Cost Anomaly Detection accumulates a spend deviation on `orders-prod`, but
  the digest email is not reviewed until the following Monday.
- 2025-07-22T09:00:00Z - CloudWatch alarm `orders-prod-checkout-read-latency-p99` (> 500 ms for 5
  minutes) fires as `ConsumedReadCapacityUnits` spikes; on-call paged.
- 2025-07-22T09:07:30Z - Checkout API logs intermittent HTTP 500 with body `Failed to retrieve
  order: ProvisionedThroughputExceededException`, even though auto scaling has already raised
  provisioned RCU from a baseline of 3,000 to its configured maximum of 20,000.
- 2025-07-22T09:16:00Z - CloudWatch Contributor Insights identifies
  `orders-pending-reconciliation-job` and `support-order-lookup` as the top RCU consumers, both
  via `Scan` rather than `Query`.
- 2025-07-22T09:24:00Z - On-call disables the reconciliation job's EventBridge rule; latency and
  RCU consumption return to baseline within 6 minutes.
- 2025-07-22T09:31:00Z - Cost Anomaly Detection alert is reviewed, confirming a $2,300/day (359%)
  spend increase over the preceding 9 days.

## Root Cause

`orders-prod` has a primary key on `order_id` and no GSI covering lookups by `customer_email` or
`status`. When PR #4471 added those two access patterns, the only available path for both was a
full-table `Scan` with a `FilterExpression`, which reads every item regardless of match count.
That alone would have been a moderate cost at daily cadence. The contributing factor was the
EventBridge schedule bug in the same PR - `rate(15 minutes)` instead of `rate(1 day)` - which ran
the scan roughly 96x more often than designed. The combined demand (~118,000 RCU per run, every
15 minutes) repeatedly outpaced auto scaling, causing throttling on unrelated checkout reads and
sustained, avoidable cost.

## Impact

- Checkout `GetItem` p99 latency rose from 8 ms to 1,850 ms during scan windows, with occasional
  HTTP 500 `ProvisionedThroughputExceededException` responses.
- DynamoDB spend rose from ~$640/day to $2,940/day, an estimated $20,700 in unplanned spend over
  9 days.
- Auto scaling repeatedly raised provisioned RCU on `orders-prod` from 3,000 toward its 20,000
  ceiling, itself a secondary cost driver.
- No customer-facing data loss or incorrect order data; impact was latency and cost.

## Detection

Primary detection was CloudWatch alarm `orders-prod-checkout-read-latency-p99` (> 500 ms for 5
minutes). Cost Anomaly Detection had flagged the spend deviation days earlier via an unmonitored
daily digest email that did not independently trigger an incident.

## Resolution

1. Used Contributor Insights to identify the two `Scan`-based consumers of read capacity.
2. Disabled the reconciliation job's EventBridge rule, restoring latency and RCU to baseline
   within 6 minutes.
3. Created GSI `customer_email-status-index` (partition key `customer_email`, sort key `status`)
   via `UpdateTable`; backfill completed in 41 minutes.
4. Migrated both consumers to `Query` against the new GSI instead of `Scan`.
5. Corrected the schedule to `rate(1 day)` and re-enabled the job.

## Action Items

1. Add a review check flagging any new `Scan` call against `orders-prod` or tables over a
   configurable item-count threshold. Owner: Platform team. Ticket: JIRA-7101.
2. Require two-person review for EventBridge schedule changes on jobs touching `orders-prod`.
   Owner: Data Platform team. Ticket: JIRA-7102.
3. Lower the Cost Anomaly Detection threshold for `orders-prod` from $500/day to $150/day and
   route alerts to PagerDuty in addition to email. Owner: SRE team. Ticket: JIRA-7103.
4. Make Contributor Insights a standing report on all production DynamoDB tables. Owner:
   Observability team. Ticket: JIRA-7104.
