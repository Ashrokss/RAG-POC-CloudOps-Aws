---
type: playbook
id: missing-index
name: Responding to a scan-driven latency and cost spike
failure_mode: missing-index
services: ["dynamodb"]
owned_by: "TBD - set in review"
---

## When you see this

Read latency degrading on a table with no corresponding traffic increase, unexplained cost growth on the table, and/or a `Scan` call showing up as the dominant consumer of read capacity.

## Mitigate

1. Use Contributor Insights (or equivalent) to identify which consumer(s) are issuing `Scan` calls against the table.
2. If a misconfigured schedule is multiplying the scan's frequency, disable or fix that schedule first - it's often the bigger lever than the scan itself.
3. Add the GSI the access pattern actually needs, and migrate the consumer from `Scan` to `Query`.

## Prevent

- Review any new `Scan` call against a production table above a configurable size threshold before it merges.
- Make Contributor Insights a standing report on production tables rather than something only pulled up during an incident.
- Require two-person review for schedule-expression changes on jobs touching high-traffic tables.
- Lower cost-anomaly-detection thresholds and route them to PagerDuty in addition to email, so a slow cost bleed doesn't wait for a latency alarm to be noticed.

## Related

- Failure mode: [Query falling back to a full table scan](../failure-modes/missing-index.md)
- Incidents: INC-2025-0702
