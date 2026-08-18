---
doc_id: "42c22167-17cf-49db-8a1e-4b1d8f2ba396"
incident_id: "INC-2025-0602"
title: "API Gateway 504 Integration Timeouts from Lambda Cold-Start Regression"
date: "2025-06-24T19:10:00Z"
severity: critical
services: ["API Gateway", "Lambda"]
region: "us-west-2"
account_id: "552013489207"
status: "resolved"
tags: ["lambda", "cold-start", "timeout", "api-gateway", "deployment"]
source: synthetic
# Extracted by hand from this document's own Impact and Detection sections
# so aggregate questions (longest detection gap, total cost, duration
# ranking) can be answered by sorting a column instead of hoping top-k
# retrieval happens to surface every relevant doc. null = not stated above.
detection_gap_minutes: 2
duration_minutes: 47
cost_usd: null
---

## Summary

A deployment of `order-enrichment-svc` (behind API `order-api-prod`, route `POST
/v2/orders/enrich`) bundled a new transitive dependency that grew the package from 46 MB to 268
MB, and the same Terraform apply reset provisioned concurrency from 20 to 0 because
`provisioned_concurrent_executions` was omitted from the module call. Resulting cold starts (p99
init duration 31,402 ms) exceeded API Gateway's fixed 29-second integration timeout, producing
HTTP 504 for 12% of requests over 47 minutes and breaching the service's 99.9% availability SLO
(actual: 91.4%).

## Timeline

- 2025-06-24T19:00:00Z - `order-enrichment-svc` version 48 promoted to the `live` alias in
  `us-west-2`; Terraform apply completes without errors.
- 2025-06-24T19:08:45Z - Traffic ramps to normal daytime volume; Lambda `Init Duration` (ARN
  `arn:aws:lambda:us-west-2:552013489207:function:order-enrichment-svc`) spikes from a ~810 ms
  baseline to a p99 of 31,402 ms.
- 2025-06-24T19:10:00Z - CloudWatch alarm `order-enrichment-5xx-rate` (metric `5XXError` > 5% for
  5 minutes) fires and pages on-call.
- 2025-06-24T19:13:20Z - On-call confirms via X-Ray and Logs Insights that requests fail with
  HTTP 504, body `{"message": "Endpoint request timed out"}`, and `IntegrationLatency` pinned at
  exactly 29,000 ms - the fixed, non-configurable API Gateway ceiling.
- 2025-06-24T19:19:05Z - Investigation traces the package growth to an unused `tensorflow` +
  `grpcio` dependency pulled in by a logging library upgrade, and finds provisioned concurrency at
  `0` on the `live` alias versus the expected `20`.
- 2025-06-24T19:24:00Z - On-call rolls the `live` alias back to version 47.
- 2025-06-24T19:31:40Z - `5XXError` returns to baseline (<0.1%); p99 `IntegrationLatency` falls to
  340 ms.
- 2025-06-24T19:57:00Z - Provisioned concurrency of 20 explicitly restored on version 47 via
  follow-up Terraform apply; incident declared resolved.

## Root Cause

The package bloat (46 MB -> 268 MB) lengthened the Lambda INIT phase from ~810 ms average to a
p99 of 31,402 ms. Independently, the same Terraform update omitted
`provisioned_concurrent_executions`, resetting it to the module default of 0. With no provisioned
concurrency to absorb the post-deploy traffic ramp, every request cold-started, and a cold start
exceeding API Gateway's fixed 29,000 ms integration timeout - not configurable for REST or HTTP
APIs - returned a 504. Either factor alone would likely have been survivable; the combination of a
much longer cold start with zero provisioned concurrency is the root cause of the timeout rate.

## Impact

- 12% of `POST /v2/orders/enrich` requests returned HTTP 504 over 47 minutes
  (19:08:45Z-19:57:00Z).
- ~9,300 order enrichment requests failed, delaying downstream fulfillment by up to 90 minutes.
- 99.9% availability SLO breached; measured availability during the window was 91.4%.
- No data loss - SQS redrive on the calling service retried all 9,300 orders successfully.

## Detection

CloudWatch alarm `order-enrichment-5xx-rate` (`5XXError` > 5% for 5 minutes) paged on-call 2
minutes after the error rate began climbing; X-Ray traces and Logs Insights confirmed the 504
pattern and exact `IntegrationLatency` value within 3 minutes.

## Resolution

1. Confirmed the failure signature (HTTP 504, `IntegrationLatency` = 29,000 ms) pointed to a
   cold-start regression, not a downstream dependency failure.
2. Rolled the `live` alias back to version 47 via `aws lambda update-alias`.
3. Verified `5XXError` and `IntegrationLatency` returned to baseline within 8 minutes.
4. Ran a follow-up Terraform apply restoring `provisioned_concurrent_executions = 20` on version
   47 to eliminate residual cold-start risk for the rest of the day's traffic.

## Action Items

1. Add a CI check that fails a Lambda build if the unzipped package exceeds 150 MB. Owner:
   Platform team. Ticket: JIRA-5011.
2. Make `provisioned_concurrent_executions` a required (non-defaulted) variable in the shared
   Lambda Terraform module, failing `terraform plan` if omitted. Owner: Infra team. Ticket:
   JIRA-5012.
3. Add a CloudWatch alarm on Lambda `Init Duration` p99 > 5,000 ms per function as a leading
   indicator. Owner: SRE team. Ticket: JIRA-5013.
4. Evaluate isolating heavy dependencies into a separate function/image so an unrelated library
   upgrade cannot bloat `order-enrichment-svc`'s package. Owner: Order Platform team. Ticket:
   JIRA-5014.
