---
type: playbook
id: connection-draining
name: Responding to requests dropped on scale-in
failure_mode: connection-draining
services: ["alb", "ec2"]
owned_by: "TBD - set in review"
---

## When you see this

`504`/connection-reset errors clustered immediately after a scale-in event, with no other change to explain them.

## Mitigate

1. Correlate the errors' timing precisely against recent scale-in/deregistration events in the load balancer's access logs.
2. Set an explicit, non-zero deregistration delay (connection draining window) on the affected target group so in-flight requests get time to complete.

## Prevent

- Set a non-zero deregistration delay as a required default in the shared target-group IaC module, so new services can't inherit an unset (zero) default.
- Add a config-lint/CI check that flags any target group resource without an explicit deregistration-delay value.
- Backport the same fix to every other target group behind an auto-scaled fleet, not just the one that surfaced the incident.

## Related

- Failure mode: [Deregistration without connection draining](../failure-modes/connection-draining.md)
- Incidents: INC-2025-0401
