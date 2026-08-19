---
doc_id: "fe5019d4-a53d-4734-8d7d-be844151c3d7"
incident_id: "INC-2025-0201"
title: "Lambda Cold-Start Latency Spike After VPC ENI Limit Exhausted"
date: "2025-04-22T09:05:00Z"
severity: high
services: ["lambda", "vpc", "ec2"]
region: "eu-west-1"
account_id: "702918447365"
status: "resolved"
tags: ["lambda", "vpc", "eni", "cold-start", "networking"]
source: synthetic
---

## Summary

Between 09:05 and 10:48 UTC on April 22, 2025, the `payments-webhook-handler` Lambda function
(VPC-attached, subnet `subnet-0a1b2c3d4e5f67890` in `payments-prod-vpc`) experienced p99 cold
start latency of 18.4 seconds, up from a 380ms baseline, and roughly 4% of invocations failed with
`EniLimitExceededException: The elastic network interface capacity for your account has been
reached in this Availability Zone`. Root cause was exhaustion of available IP addresses in subnet
`subnet-0a1b2c3d4e5f67890` (a /26 block), combined with a same-morning deploy of three new
VPC-attached Lambda functions into that subnet during a partner-driven traffic burst.

## Timeline

- 2025-04-22T08:50:00Z - Deployment rolls out three new VPC-attached Lambda functions
  (`payments-fraud-check`, `payments-currency-convert`, `payments-ledger-sync`) into
  `subnet-0a1b2c3d4e5f67890`, shared with `payments-webhook-handler`.
- 2025-04-22T09:02:00Z - A partner integration test suite sends a burst of webhook traffic
  (~1,400 req/min vs. a 90 req/min baseline), driving `payments-webhook-handler` to scale out
  rapidly.
- 2025-04-22T09:05:00Z - CloudWatch Logs Insights surfaces the first
  `EniLimitExceededException: The elastic network interface capacity for your account has been
  reached in this Availability Zone eu-west-1a`.
- 2025-04-22T09:11:00Z - CloudWatch alarm `payments-webhook-handler-Duration-p99-High` enters
  ALARM as p99 `Duration` exceeds 15,000 ms for 3 consecutive periods.
- 2025-04-22T09:16:00Z - On-call acknowledges; X-Ray traces show time concentrated in the `Init`
  phase (cold start), pointing at networking rather than application code.
- 2025-04-22T09:31:00Z - `describe-subnets` confirms `subnet-0a1b2c3d4e5f67890` has only 68
  available IPv4 addresses left, most consumed by ENIs from the four co-located Lambda functions.
- 2025-04-22T09:47:00Z - Mitigation: on-call adds a second, larger subnet,
  `subnet-0f9e8d7c6b5a43210` (/24, 251 usable addresses), to `payments-webhook-handler`'s VPC
  config via `aws lambda update-function-configuration --vpc-config`.
- 2025-04-22T10:05:00Z - New ENI allocations succeed in the added subnet; cold start p99 begins
  falling.
- 2025-04-22T10:48:00Z - p99 `Duration` returns to baseline (~410ms); `EniLimitExceededException`
  occurrences drop to zero over a rolling 15-minute window. Incident resolved.

## Root Cause

VPC-attached Lambda functions provision Hyperplane ENIs per unique subnet/security-group
combination, drawn from that subnet's available IP space. `subnet-0a1b2c3d4e5f67890` was a /26
CIDR block (59 usable addresses after AWS reservations) shared by four VPC-attached Lambda
functions plus several long-running EC2 batch workers. Deploying three additional Lambda functions
into the same subnet, combined with `payments-webhook-handler` scaling aggressively to absorb the
partner traffic burst, drove concurrent ENI/IP consumption past the subnet's available address
space. Once free IPs were exhausted, Lambda could not provision new ENIs for additional execution
environments: new invocations either queued behind slow ENI reuse cycles (causing the 18.4s p99
cold starts) or failed outright with `EniLimitExceededException` when no path to an available IP
existed. The undersized /26 subnet, sized when only one Lambda function lived in it, was the
underlying constraint; the new deploy and traffic burst were the trigger that finally exceeded it.

## Impact

- Duration: 1 hour 43 minutes (09:05-10:48 UTC) of degraded latency, with the worst 34 minutes
  (09:31-10:05 UTC) including outright failures.
- p99 latency peaked at 18.4 seconds vs. a 380ms baseline (48x increase).
- ~4% of webhook invocations (612 of ~15,300) failed with `EniLimitExceededException` and were
  retried by the partner's webhook sender per its documented retry policy; no permanent data loss.
- Partner integration team escalated to Support; no SLA credit was owed since the webhook SLA
  covers eventual delivery, not first-attempt latency.

## Detection

Detected via CloudWatch alarm `payments-webhook-handler-Duration-p99-High`, triggering when p99
`Duration` exceeds 15,000 ms for 3 consecutive 1-minute periods. The alarm fired 6 minutes after
the first `EniLimitExceededException` appeared in logs; the exception itself had no dedicated
alarm at the time of the incident.

## Resolution

1. On-call identified via X-Ray that elevated latency was concentrated in the Lambda `Init` phase,
   pointing at VPC networking rather than application logic.
2. Confirmed via `aws ec2 describe-subnets --subnet-ids subnet-0a1b2c3d4e5f67890` that available
   IP capacity was critically low.
3. Added a second subnet (`subnet-0f9e8d7c6b5a43210`, /24) to `payments-webhook-handler`'s VPC
   configuration, giving Lambda additional IP space without requiring a redeploy.
4. Monitored `EniLimitExceededException` rate and p99 `Duration` until both returned to baseline
   for 15 consecutive minutes.

## Action Items

- Migrate all VPC-attached Lambda functions in `payments-prod-vpc` onto dedicated /24 subnets
  reserved exclusively for Lambda ENIs, separate from EC2 batch workers. Owner: Networking team.
  Ticket: SRE-6203.
- Add a CloudWatch alarm on subnet available-IP count (via a scheduled Lambda publishing a custom
  metric from `describe-subnets`) at 20% remaining capacity. Owner: SRE team. Ticket: SRE-6204.
- Add `EniLimitExceededException` as its own CloudWatch Logs metric filter and alarm, rather than
  relying solely on downstream latency alarms. Owner: SRE team. Ticket: SRE-6205.
- Require a subnet capacity check in the Lambda deployment runbook before adding new
  VPC-attached functions to an existing subnet. Owner: Platform Engineering. Ticket: SRE-6206.
