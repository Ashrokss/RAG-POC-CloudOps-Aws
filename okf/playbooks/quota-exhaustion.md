---
type: playbook
id: quota-exhaustion
name: Responding to subnet IP / ENI capacity exhaustion
failure_mode: quota-exhaustion
services: ["ec2", "ecs", "lambda", "vpc"]
owned_by: "TBD - set in review"
---

## When you see this

`EniLimitExceededException`, ECS service events reporting "no Subnet in the VPC has any available IP addresses," or task/function placement failures concentrated during a scale-out event.

## Mitigate

1. Confirm available IP capacity on the affected subnet(s) directly (`describe-subnets`).
2. Add a spare or larger subnet to the affected service's network configuration for immediate headroom, and/or temporarily reduce desired counts on lower-priority services sharing the same subnet to free addresses.
3. Re-verify placement succeeds and capacity reaches its target before considering the incident resolved.

## Prevent

- Migrate shared, undersized legacy subnets to dedicated, appropriately-sized subnets per service rather than several scaling services sharing one small block.
- Alarm on subnet available-IP-address count at a percentage-remaining threshold, not only on placement failures after the fact.
- Require a subnet-capacity check in the deployment runbook before adding new VPC-attached compute to an existing subnet.

## Related

- Failure mode: [Subnet IP / ENI capacity exhausted under scale-out](../failure-modes/quota-exhaustion.md)
- Incidents: INC-2025-0201, INC-2025-0902, INC-2025-1001
