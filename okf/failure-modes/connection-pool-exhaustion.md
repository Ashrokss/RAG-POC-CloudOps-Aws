---
type: failure-mode
id: connection-pool-exhaustion
name: Unpooled connections scaling with concurrency
services: ["lambda", "rds"]
incident_ids: ["INC-2025-0101"]
---

## What it is

A Lambda function that opens a new direct database connection per invocation, with no reserved-concurrency ceiling, translates Lambda's elastic scaling directly into database connection-count scaling - so any sufficiently large traffic spike drives concurrent connections past the database's `max_connections` limit, with nothing capping it below that hard ceiling.

## Seen in

- [INC-2025-0101](../../data/raw_rca_docs/synthetic/inc-2025-0101-rds-connection-pool-exhaustion.md) - `checkout-order-processor` opened a raw `psycopg2` connection per invocation with no `ReservedConcurrentExecutions` limit; a 9x traffic spike scaled it to 2,800 concurrent executions against a database capped at 500 connections, rejecting new connections with `too many clients already` for 47 minutes.
