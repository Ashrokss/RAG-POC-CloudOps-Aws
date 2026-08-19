---
type: playbook
id: timeout
name: Responding to a fixed time ceiling being exceeded
failure_mode: timeout
services: ["api-gateway", "lambda", "step-functions"]
owned_by: "TBD - set in review"
---

## When you see this

HTTP `504`, `IntegrationLatency` pinned at exactly a fixed ceiling (e.g. API Gateway's 29,000ms), or a pipeline/job overrunning its expected completion window.

## Mitigate

1. Determine whether the timeout is intrinsic (a cold start, a package-size regression) or caused by a slow dependency backing up the whole path.
2. Intrinsic: roll back the deploy that introduced it; restore provisioned concurrency or any other setting that was reset.
3. Dependency-caused: fix the actual bottleneck (see the linked failure mode it traces back to, e.g. [iops-throttling](iops-throttling.md)) - the timeout is a symptom, not the fault.

## Prevent

- Make settings like provisioned concurrency a required (non-defaulted) variable in shared IaC modules, so a routine apply can't silently reset them.
- Alarm on cold-start / init-duration p99 as a leading indicator, before it becomes a customer-facing timeout.
- Add a CI check that fails a build if a deployable package grows past a size threshold known to correlate with cold-start regressions.

## Related

- Failure mode: [Fixed time ceiling exceeded](../failure-modes/timeout.md)
- Incidents: INC-2025-0602, INC-2025-0102
