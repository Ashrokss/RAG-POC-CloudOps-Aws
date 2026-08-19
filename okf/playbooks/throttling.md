---
type: playbook
id: throttling
name: Responding to a request-rate ceiling being hit
failure_mode: throttling
services: ["api-gateway", "eventbridge", "lambda", "kms"]
owned_by: "TBD - set in review"
---

## When you see this

`Throttles` alarms, HTTP `429`, `ThrottlingException: Rate exceeded`, or `Rate Exceeded: Reserved concurrent execution limit exceeded` in logs.

## Mitigate

1. Identify which ceiling was actually hit: an AWS account/service quota (API Gateway, KMS), a self-imposed reservation (Lambda `ReservedConcurrentExecutions`), or a downstream target being over-driven by a misfiring upstream trigger (a schedule running far more often than intended).
2. AWS-side quota (API Gateway, KMS): file an emergency Service Quota increase, and reduce demand in parallel if possible (pause a campaign, disable the misfiring schedule).
3. Self-imposed ceiling (Lambda concurrency reservation): raise it directly (`put-function-concurrency`), after confirming account-level unreserved headroom won't starve other functions.
4. Misconfigured schedule driving demand (e.g. an EventBridge rate expression): disable or correct the rule immediately rather than scaling the downstream target to absorb it.

## Prevent

- Require a Service Quota / concurrency-reservation review ahead of any planned traffic-driving event (campaign, launch, migration).
- Alert on quota *utilization* approaching the ceiling, not only on rejected requests after the ceiling is hit.
- Require two-person review for schedule-expression changes on production rules.

## Related

- Failure mode: [Request-rate ceiling exceeded](../failure-modes/throttling.md)
- Incidents: INC-2025-0601, INC-2025-0202, INC-2025-0702, INC-2025-0302
