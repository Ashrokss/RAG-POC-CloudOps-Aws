---
type: playbook
id: failover
name: Responding to a client mishandling a managed failover
failure_mode: failover
services: ["elasticache"]
owned_by: "TBD - set in review"
---

## When you see this

Connection errors appearing immediately after a maintenance-window notification or a managed failover event, and self-resolving within roughly a minute without intervention.

## Mitigate

1. Confirm via the console or an EventBridge failover event that this was an expected, provider-initiated action, not a fault.
2. Confirm the client's own retry layer absorbed the bulk of failures, and check that engine version is now consistent across all nodes.
3. Proactively notify the owning team of any requests that exhausted their retry budget during the window, rather than waiting for a customer report.

## Prevent

- Add retry-on-timeout and exponential backoff to the shared client wrapper used against the cache, and audit other services for the same gap.
- Subscribe to maintenance and failover events so on-call gets proactive notice ahead of a scheduled patch window, not just during it.
- Evaluate a topology (e.g. cluster-mode with a configuration endpoint) that resolves failover without depending on DNS TTL expiry.
- Run a periodic failover game-day against a non-production replica to validate client retry behavior before it's needed for real.

## Related

- Failure mode: [Client mishandling a transient managed failover](../failure-modes/failover.md)
- Incidents: INC-2025-0502
