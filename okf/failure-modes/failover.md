---
type: failure-mode
id: failover
name: Client mishandling a transient managed failover
services: ["elasticache"]
incident_ids: ["INC-2025-0502"]
---

## What it is

A managed cache failover (maintenance patch, node replacement) completes in seconds at the infrastructure level, but a client that has no retry/backoff on connection errors and relies on DNS TTL expiry to discover the new primary can treat that brief, self-healing topology change as a hard failure.

## Seen in

- [INC-2025-0502](../../data/raw_rca_docs/synthetic/inc-2025-0502-elasticache-failover-errors.md) - a routine engine-version patch triggered an automatic 19-second failover; with no `retry_on_timeout` configured and a 30-second DNS TTL, clients issuing writes during that window got `ConnectionError` or `READONLY` errors instead of transparently retrying, failing 2,140 writes before the outer HTTP retry layer absorbed most of them.
