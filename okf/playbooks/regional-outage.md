---
type: playbook
id: regional-outage
name: Responding to a provider-side regional capacity loss
failure_mode: regional-outage
services: ["ebs", "s3"]
owned_by: "TBD - set in review"
---

## When you see this

A sharp, region-wide error-rate spike across an AWS-managed service, with no corresponding change on your own side, and the provider's own status dashboard possibly unavailable if it depends on the affected service.

## Mitigate

1. Confirm scope via the provider's status channels, treating the primary dashboard's own unavailability as itself a signal of severity, not a lack of information.
2. There is no customer-side fix for the underlying capacity loss - focus effort on your own dependent systems' graceful degradation (serving from a fallback region or cache) rather than attempting to accelerate the provider's recovery.
3. Communicate status externally through a channel that doesn't itself depend on the affected region/service.

## Prevent

- Build read/serve paths that can fail over to data in a different region rather than depending on a single region's availability.
- Don't host your own status or monitoring dashboards on the same service or region they monitor.
- Include large-scale, simultaneous-capacity-loss scenarios in regular game-day/chaos-engineering exercises so failover paths are exercised before they're needed for real.

## Related

- Failure mode: [Provider-side regional capacity loss](../failure-modes/regional-outage.md)
- Incidents: INC-2017-0228-S3-USEAST1
