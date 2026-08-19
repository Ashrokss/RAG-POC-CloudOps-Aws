---
type: failure-mode
id: missing-index
name: Query falling back to a full table scan
services: ["dynamodb"]
incident_ids: ["INC-2025-0702"]
---

## What it is

An access pattern that isn't covered by the table's primary key or an existing GSI falls back to a full-table `Scan` with a filter, which reads every item regardless of match count. At any real table size this is far more expensive - in both latency and RCU - than the equivalent `Query`, and if the scan runs on any kind of schedule, that cost recurs every run.

## Seen in

- [INC-2025-0702](../../data/raw_rca_docs/synthetic/inc-2025-0702-dynamodb-missing-gsi.md) - two code paths queried a 42.6M-item table by `customer_email`/`status` with no supporting GSI, so both used `Scan`; an unrelated EventBridge schedule bug ran one of them 96x more often than intended (see [throttling](throttling.md)), pushing checkout read latency from 8ms to 1.85s and costing roughly $2,300/day in excess spend for 9 days before a GSI was added.
