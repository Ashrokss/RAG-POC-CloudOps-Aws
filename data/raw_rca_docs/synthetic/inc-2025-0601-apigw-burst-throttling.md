---
doc_id: "e12951e9-da01-4b96-85a6-38805cc34f85"
incident_id: "INC-2025-0601"
title: "API Gateway 429 Throttling During Marketing Push Notification Campaign"
date: "2025-06-12T14:03:00Z"
severity: high
services: ["API Gateway", "Lambda"]
region: "us-east-1"
account_id: "738491062615"
status: "resolved"
tags: ["api-gateway", "throttling", "rate-limiting", "burst-limit", "marketing-campaign"]
source: synthetic
# Extracted by hand from this document's own Impact and Detection sections
# so aggregate questions (longest detection gap, total cost, duration
# ranking) can be answered by sorting a column instead of hoping top-k
# retrieval happens to surface every relevant doc. null = not stated above.
detection_gap_minutes: 3
duration_minutes: 22
cost_usd: 12400
---

## Summary

A push notification sent to 2.1M subscribers for the "Summer Rewards" campaign drove a
near-instantaneous surge of app opens against `POST /v1/campaign/redeem` on REST API
`a1b2c3d4e5` (stage `prod`). Traffic exceeded the AWS account-level API Gateway throttle for
`us-east-1` (steady-state 10,000 RPS, burst 5,000 requests via token bucket), and 38% of
redemption requests were rejected with HTTP 429 for 22 minutes. Because the offer expired at the
end of the campaign window, throttled users could not retry, causing an estimated $12,400 in lost
conversions and 61 support tickets.

## Timeline

- 2025-06-12T14:00:00Z - Marketing sends the push notification to 2.1M devices.
- 2025-06-12T14:02:40Z - Traffic to `/v1/campaign/redeem` ramps from a baseline of ~1,200 RPS to
  a peak of 11,800 RPS within 90 seconds.
- 2025-06-12T14:03:00Z - CloudWatch alarm `campaign-api-5xx-4xx-error-rate` (metric `4XXError`,
  threshold > 25% for 3 minutes) fires and pages the on-call SRE.
- 2025-06-12T14:06:15Z - On-call confirms clients are receiving HTTP 429 with body
  `{"message":"Too Many Requests"}`; `4XXError` shows 38% of requests rejected.
- 2025-06-12T14:11:02Z - Lambda and DynamoDB integration targets rule out as the bottleneck; the
  account-level throttle (burst 5,000 / steady-state 10,000 RPS) is identified as the constraint.
- 2025-06-12T14:14:30Z - SRE files an emergency Service Quota increase request for API Gateway
  `Throttle rate` and `Throttle burst` in `us-east-1`.
- 2025-06-12T14:22:00Z - Marketing pauses the remaining push batches to reduce demand while the
  quota increase is pending.
- 2025-06-12T14:25:10Z - AWS Support approves the increase to 20,000 RPS steady-state / 10,000
  burst; 429 rate falls below 1% within 3 minutes.

## Root Cause

The API Gateway account-level (region-level) throttle for `us-east-1` remained at the AWS default
of 10,000 RPS steady-state with a 5,000-request burst (token bucket). This ceiling applies across
all APIs in the account/region combined, independent of per-method or usage-plan throttling. The
push notification produced a burst far exceeding the 5,000-request bucket within seconds,
exhausting it and causing API Gateway to reject overflow with HTTP 429 before requests reached the
backend Lambda. The trigger was the push send; the root cause is that no quota increase had been
requested despite marketing's own traffic projection - shared three days earlier - of 12,000 RPS
peak, already above the default ceiling.

## Impact

- 38% of `POST /v1/campaign/redeem` requests returned HTTP 429 for 22 minutes.
- ~54,000 redemption attempts failed; estimated $12,400 in lost promotional conversions.
- 61 support tickets referencing "reward not applying" or "error redeeming code."
- Other APIs on the account (`checkout-api`, `auth-api`) remained unaffected.

## Detection

CloudWatch alarm `campaign-api-5xx-4xx-error-rate` on the `4XXError` metric (>25% over 3 minutes)
paged on-call 3 minutes after traffic began ramping; no customer reports preceded the page.

## Resolution

1. Confirmed the 429s (`{"message":"Too Many Requests"}`) originated at the API Gateway layer,
   not the Lambda integration.
2. Filed an emergency Service Quota increase for `Throttle rate` (10,000 -> 20,000 RPS) and
   `Throttle burst` (5,000 -> 10,000) in `us-east-1`.
3. Paused remaining push batches while the increase was in flight.
4. Applied the approved increase; confirmed 429 rate fell below 1% within 3 minutes, then resumed
   the remaining push batches at a throttled send rate.

## Action Items

1. Require a Service Quota review and pre-approved increase for any campaign projected to exceed
   50% of the current account throttle limit. Owner: SRE team. Ticket: JIRA-4821.
2. Add client-side exponential backoff with jitter for HTTP 429 in the mobile redemption flow.
   Owner: Mobile team. Ticket: JIRA-4822.
3. Add a load-test step to the campaign runbook replaying projected peak RPS against a staging
   API Gateway with production-equivalent throttle settings. Owner: SRE team. Ticket: JIRA-4823.
4. Build a dashboard widget showing account-level throttle utilization vs quota across regions.
   Owner: Observability team. Ticket: JIRA-4824.
