---
type: failure-mode
id: timeout
name: Fixed time ceiling exceeded
services: ["api-gateway", "lambda", "step-functions"]
incident_ids: ["INC-2025-0602", "INC-2025-0102"]
---

## What it is

A fixed, often non-configurable time ceiling (API Gateway's 29-second integration timeout, a pipeline's expected completion window) is exceeded because something in the call path is slower than the ceiling assumes - a cold start, or a dependency backed up by its own throttling.

## Playbook

[Responding to a fixed time ceiling being exceeded](../playbooks/timeout.md)

## Seen in

- [INC-2025-0602](../../data/raw_rca_docs/synthetic/inc-2025-0602-apigw-integration-timeout.md) - a deploy dropped Lambda provisioned concurrency to 0 and grew the package to 268 MB; resulting cold starts (p99 31.4s) exceeded API Gateway's fixed 29s integration timeout, which is not configurable for REST or HTTP APIs.
- [INC-2025-0102](../../data/raw_rca_docs/synthetic/inc-2025-0102-rds-iops-throttling.md) - the nightly ETL Step Functions pipeline ran 3h12m over its ~90-minute window because its RDS dependency was IOPS-throttled (see [iops-throttling](iops-throttling.md)); two dependent Glue jobs then failed on their own 30-minute query timeout.
