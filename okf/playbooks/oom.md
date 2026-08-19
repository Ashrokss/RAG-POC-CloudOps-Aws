---
type: playbook
id: oom
name: Responding to containers being OOM-killed
failure_mode: oom
services: ["ecs"]
owned_by: "TBD - set in review"
---

## When you see this

Container exit code `137`, `stoppedReason: "OutOfMemoryError"`, tasks cycling shortly after a deploy under normal (not peak) load.

## Mitigate

1. Correlate the OOM onset with the most recent deploy and diff what changed - a dependency bump is a common, easy-to-miss cause of a memory-footprint regression.
2. Roll back to the prior task-definition revision.
3. Monitor the downstream backlog (see [backlog](backlog.md)) this may have caused, and confirm it drains once the service is stable.

## Prevent

- Add a memory-regression gate to the dependency-upgrade CI pipeline that fails the build if steady-state memory grows materially versus the previous release.
- Enable the deployment circuit breaker with automatic rollback, so a regression reverts on its own without paging on-call.
- Re-baseline the container's hard memory limit deliberately whenever a dependency upgrade is expected to change footprint, rather than leaving the limit at its pre-upgrade value.

## Related

- Failure mode: [Memory limit exceeded under normal load](../failure-modes/oom.md)
- Incidents: INC-2025-0901
