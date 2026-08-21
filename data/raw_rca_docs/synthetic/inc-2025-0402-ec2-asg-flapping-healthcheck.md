---
doc_id: "81d319d3-40d3-4f43-8af1-2b4f69167ea5"
incident_id: "INC-2025-0402"
title: "Health Check Grace Period Misconfiguration Caused a Flapping Instance-Replacement Loop"
date: "2025-04-17T13:05:00Z"
severity: critical
services: ["EC2", "Auto Scaling", "ELB"]
region: "us-west-2"
account_id: "719542860133"
status: "resolved"
tags: ["ec2", "auto-scaling", "health-checks", "deployment", "flapping"]
source: synthetic
# Extracted by hand from this document's own Impact and Detection sections
# so aggregate questions (longest detection gap, total cost, duration
# ranking) can be answered by sorting a column instead of hoping top-k
# retrieval happens to surface every relevant doc. null = not stated above.
detection_gap_minutes: 1
duration_minutes: 118
cost_usd: 380
---

## Summary

A routine deploy of `orders-api` v3.6.0 changed the JVM warm-up path so the service now takes roughly 90 seconds to pass its `/healthz` check instead of the previous 20 seconds, but the Auto Scaling group `orders-api-asg`'s `HealthCheckGracePeriod` was still set to 30 seconds. New instances were marked unhealthy by the ALB before they finished starting, the ASG terminated them and launched replacements, and those replacements hit the same 30-second grace period and were terminated in turn. The group cycled through 46 instance replacements over 118 minutes, `GroupInServiceInstances` dropped to 0 for a 22-minute full outage, and the rapid EC2 API calls eventually triggered `RequestLimitExceeded: Request limit exceeded.` on `RunInstances`. Fixed by raising the grace period to 180 seconds and rolling back the deploy.

## Timeline

- 2025-04-17T13:00:00Z - Deploy pipeline rolls out `orders-api` v3.6.0 via instance refresh on `orders-api-asg`.
- 2025-04-17T13:03:40Z - First replaced instance fails ALB health checks with `Health checks failed with these codes: [502]`; ASG activity log records "Instance i-0a3f... failed ELB health checks. Terminating instance."
- 2025-04-17T13:05:00Z - Synthetic canary alarm `prod-orders-api-canary-failure` fires; CloudWatch alarm on target group `UnHealthyHostCount` reaches 12 of 12 targets. PagerDuty pages on-call.
- 2025-04-17T13:11:00Z - On-call observes `GroupInServiceInstances` at 0 and a continuous churn of `Terminating`/`Pending` activities in the ASG activity history; declares a full outage on `orders-api`.
- 2025-04-17T13:24:00Z - EC2 API begins returning `RequestLimitExceeded: Request limit exceeded.` on `RunInstances` calls from the ASG service-linked role, slowing replacement launches further.
- 2025-04-17T13:33:00Z - On-call suspends the `Launch` and `Terminate` scaling processes on `orders-api-asg` via `aws autoscaling suspend-processes` to stop the churn.
- 2025-04-17T13:35:00Z - Root cause traced to the mismatch between the app's new ~90s startup time and the ASG's 30-second `HealthCheckGracePeriod`; on-call manually launches 6 instances directly and waits for them to warm up before registering.
- 2025-04-17T14:58:00Z - `orders-api-asg` `HealthCheckGracePeriod` updated to 180 seconds, scaling processes resumed, v3.6.0 confirmed stable with no further terminations. Incident closed.

## Root Cause

The ASG's health check type was `ELB`, meaning an instance is considered for termination based on ALB target health rather than just the EC2 instance status check, and its `HealthCheckGracePeriod` of 30 seconds predated a change in `orders-api` v3.6.0 that added a synchronous cache-warming step to application startup, extending time-to-healthy from about 20 seconds to about 90 seconds. Because the grace period expired before the new instances could pass their first health check, the ASG interpreted a still-starting instance as failed and replaced it, and each replacement hit the identical timing problem — a self-sustaining flapping loop. The v3.6.0 deploy was the trigger; the stale, too-short grace period relative to actual startup time is the root cause of the loop not self-correcting.

## Impact

`orders-api` had zero in-service instances for 22 minutes (13:11-13:33 UTC), a full outage for order placement and order-status APIs, followed by a further 96 minutes of degraded capacity while replacements were launched manually. Estimated 8,900 failed order-related API calls returned `503 Service Unavailable`. Wasted compute from the 46 replacement cycles was approximately $380. No orders or order data were lost; in-flight orders queued in SQS and were processed once the service recovered.

## Detection

Detected by the synthetic canary alarm `prod-orders-api-canary-failure` and the target group `UnHealthyHostCount` alarm, both firing at 13:05:00 UTC, 1 minute 20 seconds after the first health-check failure.

## Resolution

1. Suspended ASG `Launch`/`Terminate` processes to halt the replacement loop.
2. Manually launched and warmed 6 instances outside the ASG's automated health-check cycle to restore service.
3. Increased `HealthCheckGracePeriod` on `orders-api-asg` from 30 to 180 seconds.
4. Resumed automated scaling processes and verified stability over one full deploy cycle.

## Action Items

- Set `HealthCheckGracePeriod` per service based on measured p99 startup time plus a 2x safety margin, and require it in the service's deploy manifest. Owner: orders-team, JIRA-5210.
- Add an alarm on `GroupTerminatingInstances` rate to catch replacement loops within 2 minutes instead of relying solely on health-check alarms. Owner: observability-team, JIRA-5211.
- Require a canary/staging soak before instance-refresh deploys touch startup-path code. Owner: release-engineering, JIRA-5212.
