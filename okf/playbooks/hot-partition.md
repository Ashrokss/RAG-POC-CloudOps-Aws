---
type: playbook
id: hot-partition
name: Responding to a single partition-key absorbing all write traffic
failure_mode: hot-partition
services: ["dynamodb"]
owned_by: "TBD - set in review"
---

## When you see this

`ProvisionedThroughputExceededException` on writes despite table-level consumed capacity sitting well under provisioned throughput; throttled requests all share one partition-key value.

## Mitigate

1. Confirm the throttling is isolated to a single partition key, not overall table capacity - adding table-level capacity will not fix this.
2. Pause or throttle the write source at the application layer until a sharding fix is ready.
3. Redesign the write path to spread the key (e.g. a hashed shard suffix) across multiple logical partitions, and cap write concurrency with backoff while re-running.

## Prevent

- Apply the write-sharded key pattern to every bulk-write path against the affected table, not just the one that surfaced the incident.
- Add a pre-import validation step that estimates projected write capacity per partition key against the per-partition ceiling before a bulk job runs.
- Lower the throttled-write alarm threshold for earlier detection than "already exceeding capacity for several minutes."

## Related

- Failure mode: [Single partition key absorbing all write traffic](../failure-modes/hot-partition.md)
- Incidents: INC-2025-0701
