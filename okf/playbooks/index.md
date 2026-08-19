# Playbooks

18 remediation runbooks, one per failure mode: what to look for, how to mitigate it immediately,
and how to prevent it recurring - synthesized from the Resolution and Action Items sections of the
incidents that exhibit each failure mode, not copied from any single incident's specifics.

* [backlog](backlog.md) - Responding to a queue backing up behind an impaired consumer → [failure mode](../failure-modes/backlog.md)
* [cert-expiry](cert-expiry.md) - Responding to an expired certificate → [failure mode](../failure-modes/cert-expiry.md)
* [config-regression](config-regression.md) - Responding to a silent config or dependency regression → [failure mode](../failure-modes/config-regression.md)
* [connection-draining](connection-draining.md) - Responding to requests dropped on scale-in → [failure mode](../failure-modes/connection-draining.md)
* [connection-pool-exhaustion](connection-pool-exhaustion.md) - Responding to unpooled connections scaling with concurrency → [failure mode](../failure-modes/connection-pool-exhaustion.md)
* [eviction](eviction.md) - Responding to a cache eviction storm → [failure mode](../failure-modes/eviction.md)
* [failover](failover.md) - Responding to a client mishandling a managed failover → [failure mode](../failure-modes/failover.md)
* [health-check-flapping](health-check-flapping.md) - Responding to a health-check replacement loop → [failure mode](../failure-modes/health-check-flapping.md)
* [hot-partition](hot-partition.md) - Responding to a single partition-key absorbing all write traffic → [failure mode](../failure-modes/hot-partition.md)
* [iops-throttling](iops-throttling.md) - Responding to a provisioned IOPS ceiling being saturated → [failure mode](../failure-modes/iops-throttling.md)
* [missing-index](missing-index.md) - Responding to a scan-driven latency and cost spike → [failure mode](../failure-modes/missing-index.md)
* [oom](oom.md) - Responding to containers being OOM-killed → [failure mode](../failure-modes/oom.md)
* [port-exhaustion](port-exhaustion.md) - Responding to a NAT Gateway connection ceiling being exceeded → [failure mode](../failure-modes/port-exhaustion.md)
* [quota-exhaustion](quota-exhaustion.md) - Responding to subnet IP / ENI capacity exhaustion → [failure mode](../failure-modes/quota-exhaustion.md)
* [regional-outage](regional-outage.md) - Responding to a provider-side regional capacity loss → [failure mode](../failure-modes/regional-outage.md)
* [replication-lag](replication-lag.md) - Responding to a replication backlog served as current → [failure mode](../failure-modes/replication-lag.md)
* [throttling](throttling.md) - Responding to a request-rate ceiling being hit → [failure mode](../failure-modes/throttling.md)
* [timeout](timeout.md) - Responding to a fixed time ceiling being exceeded → [failure mode](../failure-modes/timeout.md)
