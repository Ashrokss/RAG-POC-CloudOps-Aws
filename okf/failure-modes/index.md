# Failure modes

18 failure modes named across `../services/*.md`'s "Known failure modes" sections, each grounded
in the actual incident RCA text rather than the service files' one-line descriptions. Every entry
links forward to a remediation playbook and, where the underlying incident exhibits more than one
failure mode, sideways to the related ones (e.g. `backlog` names both `throttling` and `oom` as the
consumer-side impairments that cause it).

* [backlog](backlog.md) - Queue growing behind an impaired consumer → [playbook](../playbooks/backlog.md)
* [cert-expiry](cert-expiry.md) - Certificate renewal silently broken → [playbook](../playbooks/cert-expiry.md)
* [config-regression](config-regression.md) - Silent config or dependency regression → [playbook](../playbooks/config-regression.md)
* [connection-draining](connection-draining.md) - Deregistration without connection draining → [playbook](../playbooks/connection-draining.md)
* [connection-pool-exhaustion](connection-pool-exhaustion.md) - Unpooled connections scaling with concurrency → [playbook](../playbooks/connection-pool-exhaustion.md)
* [eviction](eviction.md) - Eviction policy unable to reclaim memory → [playbook](../playbooks/eviction.md)
* [failover](failover.md) - Client mishandling a transient managed failover → [playbook](../playbooks/failover.md)
* [health-check-flapping](health-check-flapping.md) - Health check flapping under a self-reinforcing loop → [playbook](../playbooks/health-check-flapping.md)
* [hot-partition](hot-partition.md) - Single partition key absorbing all write traffic → [playbook](../playbooks/hot-partition.md)
* [iops-throttling](iops-throttling.md) - Provisioned IOPS ceiling saturated → [playbook](../playbooks/iops-throttling.md)
* [missing-index](missing-index.md) - Query falling back to a full table scan → [playbook](../playbooks/missing-index.md)
* [oom](oom.md) - Memory limit exceeded under normal load → [playbook](../playbooks/oom.md)
* [port-exhaustion](port-exhaustion.md) - NAT Gateway per-destination connection ceiling exceeded → [playbook](../playbooks/port-exhaustion.md)
* [quota-exhaustion](quota-exhaustion.md) - Subnet IP / ENI capacity exhausted under scale-out → [playbook](../playbooks/quota-exhaustion.md)
* [regional-outage](regional-outage.md) - Provider-side regional capacity loss → [playbook](../playbooks/regional-outage.md)
* [replication-lag](replication-lag.md) - Replication backlog served as if current → [playbook](../playbooks/replication-lag.md)
* [throttling](throttling.md) - Request-rate ceiling exceeded → [playbook](../playbooks/throttling.md)
* [timeout](timeout.md) - Fixed time ceiling exceeded → [playbook](../playbooks/timeout.md)
