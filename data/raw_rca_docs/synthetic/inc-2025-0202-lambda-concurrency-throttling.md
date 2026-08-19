---
doc_id: "00d240fe-644d-450e-aa61-cb7d3c208ad5"
incident_id: "INC-2025-0202"
title: "Lambda Throttling from Reserved-Concurrency Misconfiguration During Traffic Spike"
date: "2025-05-30T17:12:00Z"
severity: high
services: ["lambda", "sqs", "api-gateway"]
region: "us-east-1"
account_id: "418773529104"
status: "resolved"
tags: ["lambda", "concurrency", "throttling", "sqs"]
source: synthetic
---

## Summary

During a product-launch traffic spike on May 30, 2025, the `notification-dispatcher` Lambda
function throttled for 38 minutes, rejecting 71% of invocations with
`Rate Exceeded: Reserved concurrent execution limit exceeded` because a prior change had fixed its
`ReservedConcurrentExecutions` at 50 - a value calculated for average load months earlier and
never revisited - while the account's unreserved concurrency pool sat mostly idle. The mismatch
backed up over 210,000 messages in the upstream SQS queue `notification-dispatch-queue`; 312
messages aged past their retry limit and landed in the dead-letter queue.

## Timeline

- 2025-05-30T17:00:00Z - Product launch announcement goes out; `POST /v1/notify` volume rises from
  ~600 req/min to ~9,200 req/min within 8 minutes.
- 2025-05-30T17:08:00Z - `notification-dispatch-queue` `ApproximateNumberOfMessagesVisible` climbs
  sharply as its consumer, `notification-dispatcher`, cannot keep pace.
- 2025-05-30T17:12:00Z - CloudWatch alarm `notification-dispatcher-Throttles-High` enters ALARM as
  `Throttles` exceeds 100/min for 3 consecutive periods. Logs show
  `Rate Exceeded: Reserved concurrent execution limit exceeded` on most invocation attempts.
- 2025-05-30T17:19:00Z - On-call acknowledges; `aws lambda get-function-concurrency
  --function-name notification-dispatcher` confirms `ReservedConcurrentExecutions: 50`, set during
  a March 2025 cost-optimization pass and never adjusted since.
- 2025-05-30T17:24:00Z - `ApproximateNumberOfMessagesVisible` peaks at 214,300 messages, versus a
  typical steady-state depth under 500.
- 2025-05-30T17:31:00Z - Mitigation: on-call raises `ReservedConcurrentExecutions` to 800 via
  `aws lambda put-function-concurrency --function-name notification-dispatcher
  --reserved-concurrent-executions 800`, after confirming account-level unreserved headroom
  (~950) could absorb the increase.
- 2025-05-30T17:34:00Z - Throttle rate drops from 71% to under 5% within 3 minutes.
- 2025-05-30T17:50:00Z - Queue depth begins draining at ~6,800 messages/minute.
- 2025-05-30T18:47:00Z - Queue depth returns to baseline (<500). 312 messages had exceeded
  `maxReceiveCount: 6` and were routed to `notification-dispatch-dlq`. Incident resolved.

## Root Cause

`ReservedConcurrentExecutions` on `notification-dispatcher` had been explicitly fixed at 50 in
March 2025 as a cost-control measure, based on average traffic at that time (peak concurrency
observed then: ~35). This reservation is a hard ceiling enforced independently of account-level
unreserved concurrency headroom - unlike unreserved functions, a function with an explicit
reservation cannot borrow from the shared pool even when that pool is nearly empty. No process
existed to review or scale the reservation ahead of planned launches. When the launch-driven spike
pushed demand for concurrent executions past 50, every invocation attempt beyond that ceiling was
rejected synchronously with `Rate Exceeded: Reserved concurrent execution limit exceeded`,
regardless of unreserved capacity elsewhere in the account. Because the function is SQS-triggered,
throttled polls caused the event source mapping to back off, and messages accumulated in the
queue faster than the capped consumer could drain them.

## Impact

- Duration: 38 minutes of active throttling (17:12-17:50 UTC); full recovery by 18:47 UTC (1h35m
  total).
- Peak throttle rate of 71% of invocation attempts (17:12-17:31 UTC).
- Median notification delivery delay rose from under 5 seconds to ~24 minutes at peak backlog.
- 312 messages exceeded `maxReceiveCount: 6` and were moved to `notification-dispatch-dlq`,
  requiring manual reprocessing and product-team sign-off before redelivery.
- No customer-facing checkout or account impact; limited to the notification subsystem.

## Detection

Detected via CloudWatch alarm `notification-dispatcher-Throttles-High`, triggering when
`Throttles` exceeds 100 in a 1-minute period for 3 consecutive periods. It fired 4 minutes after
the traffic spike began and 12 minutes before queue depth peaked, but the fixed reservation itself
was not something the alarm could resolve automatically.

## Resolution

1. On-call confirmed the active concurrency ceiling via `get-function-concurrency` and correlated
   it with the launch traffic ramp.
2. Verified account-level unreserved headroom (~950) before raising the reservation, to avoid
   starving other production functions.
3. Increased `ReservedConcurrentExecutions` to 800 via `put-function-concurrency`, applied
   immediately with no redeploy required.
4. Monitored SQS `ApproximateNumberOfMessagesVisible` and Lambda `Throttles` until both returned
   to baseline.
5. Coordinated with the product team to manually redrive the 312 dead-lettered messages.

## Action Items

- Replace the fixed `ReservedConcurrentExecutions` of 50 with a smaller floor guarantee (e.g. 100)
  plus documented reliance on unreserved pool headroom, rather than treating it as a hard
  cost-control cap. Owner: Messaging team. Ticket: SRE-7301.
- Add a pre-launch checklist requiring capacity review of Lambda concurrency reservations for
  functions in a marketing launch's critical path. Owner: SRE team. Ticket: SRE-7302.
- Alert on any message arrival in `notification-dispatch-dlq`, rather than only reviewing the DLQ
  after an incident. Owner: Messaging team. Ticket: SRE-7303.
