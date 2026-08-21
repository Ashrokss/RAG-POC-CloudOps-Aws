---
type: playbook
id: connection-pool-exhaustion
name: Responding to unpooled connections scaling with concurrency
failure_mode: connection-pool-exhaustion
services: ["lambda", "rds"]
owned_by: "TBD - set in review"
---

## When you see this

A database rejecting new connections at its `max_connections` ceiling while the calling compute's concurrency is scaling freely with no cap of its own.

## Mitigate

1. Cap the consumer's concurrency (e.g. Lambda `ReservedConcurrentExecutions`) immediately, forcing excess demand to throttle at the compute layer instead of exhausting the database.
2. Confirm downstream error rates and connection counts recover once the cap takes effect.
3. Monitor for a sustained period before declaring resolution - a fixed ceiling only holds until the next larger spike unless a permanent fix follows.

## Prevent

- Migrate to a connection pooler (e.g. RDS Proxy) so elastic compute scaling doesn't translate 1:1 into database connection-count scaling.
- Set a permanent concurrency ceiling on every function that connects directly to the database, sized to keep peak connections under a safe fraction of `max_connections`.
- Add a composite alarm correlating database connection count with the calling compute's concurrency, for warning before the ceiling is reached.
- Load-test the path at several times steady-state traffic ahead of any planned demand spike.

## Related

- Failure mode: [Unpooled connections scaling with concurrency](../failure-modes/connection-pool-exhaustion.md)
- Incidents: INC-2025-0101
