---
doc_id: "ff1500b6-527b-442a-ba8e-6fc87c224de3"
incident_id: "INC-2025-0101"
title: "RDS Connection Pool Exhaustion from Unbounded Lambda Concurrency Spike"
date: "2025-02-11T14:32:00Z"
severity: critical
services: ["rds", "lambda", "api-gateway"]
region: "us-east-1"
account_id: "418773529104"
status: "resolved"
tags: ["rds", "lambda", "connection-pool", "concurrency", "postgres"]
source: synthetic
# Extracted by hand from this document's own Impact and Detection sections
# so aggregate questions (longest detection gap, total cost, duration
# ranking) can be answered by sorting a column instead of hoping top-k
# retrieval happens to surface every relevant doc. null = not stated above.
detection_gap_minutes: 3
duration_minutes: 47
cost_usd: 61000
---

## Summary

On February 11, 2025, the `orders-api` service began returning HTTP 500 errors to roughly 62% of
checkout requests for 47 minutes after a marketing push notification drove a 9x spike in traffic.
The spike caused the `checkout-order-processor` Lambda function to scale from a steady-state
concurrency of ~40 to 2,800 concurrent executions. Each execution opened its own direct connection
to the `orders-prod-pg` RDS PostgreSQL instance (db.r6g.2xlarge, max_connections=500) instead of
using a pooled connection, exhausting the connection limit and causing new connections to be
rejected with `FATAL: sorry, too many clients already` and `connection refused: too many clients
already`. Downstream services sharing the same database, including `inventory-service` and
`invoice-service`, were also degraded as a result.

## Timeline

- 2025-02-11T14:29:00Z - Marketing push notification sent to 1.2M subscribers advertising a flash
  sale, driving a sharp increase in traffic to `POST /v2/checkout`.
- 2025-02-11T14:32:00Z - CloudWatch alarm `orders-prod-pg-DatabaseConnections-High` enters ALARM
  state after `DatabaseConnections` exceeds 480 out of a max of 500 for 3 consecutive 60-second
  periods.
- 2025-02-11T14:33:41Z - PagerDuty incident INC-2025-0101 auto-created; on-call SRE (secondary
  rotation) acknowledges within 2 minutes.
- 2025-02-11T14:38:00Z - Investigation confirms Lambda concurrent executions climbed to 2,800
  (reserved concurrency was unset). Application logs show repeated
  `psycopg2.OperationalError: FATAL: sorry, too many clients already` and
  `connection refused: too many clients already` against
  `orders-prod-pg.cluster-cabcxyz123.us-east-1.rds.amazonaws.com:5432`.
- 2025-02-11T14:41:00Z - `inventory-service` and `invoice-service` begin emitting elevated 5xx
  rates (18% and 11% respectively) as they compete for the same connection slots on
  `orders-prod-pg`.
- 2025-02-11T14:47:00Z - Mitigation: on-call sets `ReservedConcurrentExecutions=100` on
  `checkout-order-processor` via `aws lambda put-function-concurrency` to cap simultaneous
  connections and force throttling (HTTP 429 from API Gateway) instead of database exhaustion.
- 2025-02-11T14:53:00Z - `DatabaseConnections` drops below 350; checkout error rate falls to 4%.
- 2025-02-11T15:19:00Z - Error rate returns to baseline (<0.2%) as traffic from the flash sale
  tapers off. Incident declared resolved.
- 2025-02-11T15:45:00Z - Incident commander closes INC-2025-0101; follow-up items filed in Jira
  under `SRE-4471`.

## Root Cause

`checkout-order-processor` opened a new raw PostgreSQL connection per invocation via
`psycopg2.connect()` inside the handler instead of reusing pooled connections (e.g. RDS Proxy).
With no `ReservedConcurrentExecutions` limit set, the function scaled freely on the account's
unreserved concurrency pool, reaching 2,800 concurrent executions during the spike. Each execution
held its own connection for the request duration (avg. 340ms), so at peak, 2,100+ simultaneous
connections were attempted against a database with `max_connections=500`. No connection pooling
combined with no concurrency ceiling meant Lambda's elastic scaling translated directly into
database connection-count scaling, with nothing capping it below the database's hard limit. The
push notification was the trigger, not the root cause; any sufficiently large traffic spike would
have produced the same outcome.

## Impact

- Duration: 47 minutes of degraded service (14:32 UTC - 15:19 UTC).
- 62% of `POST /v2/checkout` requests returned HTTP 500 during peak impact (14:38-14:53 UTC).
- Estimated 8,400 failed checkout attempts; estimated revenue impact of $61,000 (avg. order value
  $72.60, plus observed cart-abandonment following failed checkouts).
- `inventory-service` and `invoice-service` saw secondary 5xx elevation (18% and 11% peak) from
  shared database contention.
- SLO breach: checkout API's 99.9% monthly availability SLO was breached for February 2025
  (measured: 99.83%).

## Detection

Detected via CloudWatch alarm `orders-prod-pg-DatabaseConnections-High`, which triggers when
`DatabaseConnections` on `orders-prod-pg` exceeds 480 (96% of the 500-connection limit) for 3
consecutive 60-second periods. Time from trigger event to alarm was ~3 minutes; alarm to
acknowledgment was 1 minute 41 seconds.

## Resolution

1. On-call applied an emergency cap via `aws lambda put-function-concurrency
   --function-name checkout-order-processor --reserved-concurrent-executions 100`, forcing excess
   invocations to throttle (`TooManyRequestsException`) at the Lambda layer instead of exhausting
   database connections.
2. API Gateway's existing retry/backoff converted hard 500s into client-visible 429s with
   `Retry-After` headers for a subset of users.
3. Confirmed `DatabaseConnections` stabilized below 350 and checkout success rate recovered.
4. Monitored for 30 minutes post-mitigation before declaring resolution.

## Action Items

- Migrate `checkout-order-processor` to RDS Proxy (`orders-prod-pg-proxy`) to pool connections
  across concurrent Lambda executions. Owner: Platform Data team. Ticket: SRE-4471.
- Set a permanent `ReservedConcurrentExecutions` ceiling on all Lambda functions that connect
  directly to `orders-prod-pg`, sized to keep peak connections under 70% of `max_connections`.
  Owner: Checkout team. Ticket: SRE-4472.
- Add a CloudWatch composite alarm correlating `DatabaseConnections` with Lambda
  `ConcurrentExecutions` for early warning before the connection ceiling is reached. Owner: SRE
  team. Ticket: SRE-4473.
- Load-test the checkout path at 10x steady-state traffic ahead of the next planned marketing
  campaign. Owner: QA/Performance team. Ticket: SRE-4474.
