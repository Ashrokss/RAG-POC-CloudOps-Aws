---
type: playbook
id: health-check-flapping
name: Responding to a health-check replacement loop
failure_mode: health-check-flapping
services: ["alb", "ec2", "ecs"]
owned_by: "TBD - set in review"
---

## When you see this

`UnhealthyHostCount` alarms, an ASG/service activity log showing repeated instance or task termination and replacement, healthy host count oscillating rather than settling.

## Mitigate

1. Suspend the automated replacement loop (ASG `Launch`/`Terminate` processes, or equivalent) before it churns further - stop the bleeding before diagnosing.
2. Identify what changed relative to the health check's assumptions: a startup-time regression outrunning the grace period, or a resource-limit change (memory, CPU) causing latency under the check's own load.
3. Manually restore capacity outside the automated cycle while the underlying fix is applied.
4. Resume automated scaling only after confirming the fix holds across a full cycle.

## Prevent

- Size the health-check grace period to measured p99 startup time plus a safety margin, and require it in the service's deploy manifest rather than leaving it at a stale default.
- Remove hard dependencies (e.g. a synchronous database call) from the health-check endpoint itself, so the check isn't vulnerable to the same load-induced latency it exists to detect.
- Alarm directly on termination/replacement rate, not only on downstream health metrics, so a loop is caught within minutes rather than after it's already caused an outage.

## Related

- Failure mode: [Health check flapping under a self-reinforcing loop](../failure-modes/health-check-flapping.md)
- Incidents: INC-2025-0402, INC-2025-0802
