---
type: playbook
id: eviction
name: Responding to a cache eviction storm
failure_mode: eviction
services: ["elasticache"]
owned_by: "TBD - set in review"
---

## When you see this

`Evictions` metric spiking, memory usage approaching `maxmemory`, and/or writes rejected with `OOM command not allowed when used memory > 'maxmemory'`.

## Mitigate

1. Sample the keyspace (`redis-cli --bigkeys` or equivalent) to identify the write path producing non-expiring keys.
2. Set `maxmemory-policy` to an all-keys-eligible policy (e.g. `allkeys-lru`) as an immediate stopgap so every key becomes evictable, not just TTL-bearing ones.
3. Roll back the deploy that dropped the TTL, and clean up accumulated non-expiring keys once traffic stabilizes.

## Prevent

- Add a CI check that rejects any cache write on a session/short-lived-data path lacking an explicit expiry.
- Default to an all-keys-eligible eviction policy permanently rather than reverting to a TTL-only one, unless something specifically depends on non-expiring keys.
- Add a circuit breaker around any fallback path (e.g. a database read-through) so a cache outage degrades gracefully instead of forwarding full load downstream.
- Dashboard the percentage of keys without a TTL per cluster, alerting above a small threshold.

## Related

- Failure mode: [Eviction policy unable to reclaim memory](../failure-modes/eviction.md)
- Incidents: INC-2025-0501
