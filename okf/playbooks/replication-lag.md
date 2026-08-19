---
type: playbook
id: replication-lag
name: Responding to a replication backlog served as current
failure_mode: replication-lag
services: ["s3"]
owned_by: "TBD - set in review"
---

## When you see this

A replication-latency alarm, and/or downstream reads (a cache, a secondary region) visibly serving stale data relative to the source.

## Mitigate

1. Identify the actual bottleneck in the replication path - commonly a dependency's own rate limit (see [throttling](throttling.md)), not a replication-engine problem itself.
2. Request an emergency quota increase on the blocking dependency, and pause the write source generating the backlog if it's still running.
3. Once replication catches up, invalidate or refresh any downstream cache explicitly - stale reads can outlive the backlog itself if nothing forces a refresh.

## Prevent

- Enable a replication-SLA feature with built-in backpressure alerting (e.g. S3 Replication Time Control) instead of relying on a lagging-latency alarm alone.
- Rate-limit bulk write jobs so they don't burst a full day's payload into replication in one window.
- Add a staleness check so reads fail over to the source region directly once lag exceeds a threshold, instead of treating the replica as authoritative regardless of lag.
- Lower the replication-latency alarm threshold and add a rate-of-change alarm, since a slowly climbing, never-recovering lag can take hours to cross an absolute threshold.

## Related

- Failure mode: [Replication backlog served as if current](../failure-modes/replication-lag.md)
- Incidents: INC-2025-0302
