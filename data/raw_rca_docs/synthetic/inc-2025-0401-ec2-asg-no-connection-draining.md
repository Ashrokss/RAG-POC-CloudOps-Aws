---
doc_id: "2317f2b0-e9df-4bb2-9a64-9e323dc17452"
incident_id: "INC-2025-0401"
title: "ASG Scale-In Dropped In-Flight Checkout Requests Due to Missing Connection Draining"
date: "2025-04-01T18:22:00Z"
severity: high
services: ["EC2", "Auto Scaling", "ELB"]
region: "us-east-1"
account_id: "719542860133"
status: "resolved"
tags: ["ec2", "auto-scaling", "load-balancer", "connection-draining", "scale-in"]
source: synthetic
---

## Summary

A traffic spike from a flash promotion caused Auto Scaling group `checkout-service-asg` to scale out to 20 instances, then scale back in to 12 as traffic dropped 40 minutes later. The target group `arn:aws:elasticloadbalancing:us-east-1:719542860133:targetgroup/checkout-tg/8a2f5c91e4b7d3a0` had `deregistration_delay.timeout_seconds` set to `0`, so the ALB deregistered and the ASG terminated 8 instances with zero connection draining. Requests in flight on those instances were cut mid-response: clients received `504 Gateway Timeout` and connection-reset errors for 1,140 requests over roughly 6 minutes, a 3.7% error rate on the checkout path during the scale-in window. Fixed by setting deregistration delay to 300 seconds and adding a scale-in cooldown.

## Timeline

- 2025-04-01T17:40:00Z - Flash promotion traffic causes `checkout-service-asg` target tracking policy (`ASGAverageCPUUtilization` target 60%) to scale out from 12 to 20 instances.
- 2025-04-01T18:15:00Z - Promotional traffic subsides; average CPU drops below the 60% target for the scale-in cooldown period.
- 2025-04-01T18:22:14Z - ASG scale-in activity terminates 8 instances within a 90-second window; ALB immediately deregisters them from `checkout-tg` with `deregistration_delay.timeout_seconds=0`.
- 2025-04-01T18:22:30Z - CloudWatch alarm `checkout-alb-5xx-high` fires on `HTTPCode_Target_5XX_Count > 50` over 1 minute; PagerDuty pages on-call.
- 2025-04-01T18:24:00Z - On-call pulls ALB access logs, finds 1,140 entries with `target_status_code 000` and `error_reason "TargetConnectionTermination"` clustered in the 18:22-18:28 window.
- 2025-04-01T18:31:00Z - Root cause identified as the target group's zero-second deregistration delay; on-call updates `checkout-tg` attribute to `deregistration_delay.timeout_seconds=300` via the console.
- 2025-04-01T18:34:00Z - New scale-in events confirmed to drain connections correctly; 5xx rate returns to baseline (under 0.05%).
- 2025-04-01T19:05:00Z - Incident closed after 30 minutes of stable error rates.

## Root Cause

`checkout-tg`'s `deregistration_delay.timeout_seconds` attribute was left at `0` when the target group was created from a Terraform module that did not set an explicit default, so the ALB's built-in connection draining was effectively disabled. When the ASG terminated an instance, the ALB deregistered the target and stopped routing new connections to it immediately, but any request already in flight on that instance's open TCP connections was abruptly reset rather than being allowed to complete before deregistration took effect. The scale-in event itself (a target-tracking policy correctly reacting to a real CPU drop) was the trigger; the missing connection-draining window is the root cause of requests being dropped rather than being cleanly finished.

## Impact

1,140 requests failed with `504 Gateway Timeout` or connection-reset errors between 18:22:14 and 18:28:00 UTC, a 3.7% error rate on the checkout service during that window. An estimated 190 checkout sessions were abandoned; no duplicate charges occurred since payment capture had not yet been invoked on the failed requests. Total customer-facing degradation lasted approximately 6 minutes.

## Detection

Detected by CloudWatch alarm `checkout-alb-5xx-high`, defined on `HTTPCode_Target_5XX_Count > 50` over a 1-minute period, which fired 16 seconds after the first terminations began. PagerDuty paged the on-call SRE within 45 seconds of the alarm.

## Resolution

1. Identified the terminated targets and correlated their instance IDs with the ALB access log `TargetConnectionTermination` entries.
2. Set `deregistration_delay.timeout_seconds` to `300` on `checkout-tg` to allow in-flight requests up to 5 minutes to complete before a deregistering target stops receiving traffic.
3. Verified the fix by observing the next natural scale-in event drain cleanly with zero 5xx errors.
4. Backported the same attribute value to the other 6 target groups behind ASGs in the account.

## Action Items

- Add `deregistration_delay.timeout_seconds = 300` as an explicit default in the shared `alb-target-group` Terraform module so new services can't inherit the unset (zero) default. Owner: platform-infra-team, JIRA-5104.
- Add a scale-in cooldown of 180 seconds to `checkout-service-asg` to reduce thrash after short traffic spikes. Owner: checkout-team, JIRA-5105.
- Add a config linter check in CI that flags any target group resource without an explicit `deregistration_delay.timeout_seconds`. Owner: platform-infra-team, JIRA-5106.
