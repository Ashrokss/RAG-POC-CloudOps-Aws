---
doc_id: "90e3ea03-4631-45d3-a7ee-349ab267ccba"
incident_id: "INC-2025-0902"
title: "ECS Fargate Scale-Out Stalled by VPC Subnet IP Address Exhaustion"
date: "2025-09-02T09:15:00Z"
severity: high
services: ["ecs", "fargate", "vpc", "ec2"]
region: "eu-west-1"
account_id: "558312940071"
status: "resolved"
tags: ["networking", "capacity", "vpc", "deployment", "eni"]
source: synthetic
# Extracted by hand from this document's own Impact and Detection sections
# so aggregate questions (longest detection gap, total cost, duration
# ranking) can be answered by sorting a column instead of hoping top-k
# retrieval happens to surface every relevant doc. null = not stated above.
detection_gap_minutes: 6
duration_minutes: 54
cost_usd: 41000
---

## Summary

An Application Auto Scaling event scaled `prod-checkout-svc` from 40 to 160 Fargate tasks in response
to a flash-sale traffic surge. Because ECS tasks in `awsvpc` network mode each consume a dedicated
elastic network interface and private IP address, and the two production subnets backing the service
were provisioned as `/26` blocks already shared with two other services, only about 23 free IP
addresses remained across both subnets. The overwhelming majority of new task placements failed at
the ENI-creation step, capping real capacity far below demand and driving checkout error rates and
latency up for roughly 50 minutes during the sale window.

## Timeline

- **09:15 UTC** - Application Auto Scaling triggers a target-tracking scale-out of
  `prod-checkout-svc` from 40 to 160 desired tasks in response to a flash-sale traffic surge.
- **09:18 UTC** - The ECS scheduler launches the first ~20 new tasks successfully, then task
  placements begin failing.
- **09:24 UTC** - CloudWatch alarm `checkout-svc-DesiredVsRunning-Mismatch`
  (`RunningTaskCount < 80%` of `DesiredCount` for 5 minutes) fires and pages on-call.
- **09:31 UTC** - On-call reviews ECS service events and finds repeated entries: "service
  prod-checkout-svc was unable to place a task because no Subnet in the VPC has any available IP
  addresses."
- **09:40 UTC** - `aws ec2 describe-subnets` confirms `subnet-0a1b2c3d4e5f6a7b8` (eu-west-1a) has
  `AvailableIpAddressCount: 0` and `subnet-0b2c3d4e5f6a7b8c9` (eu-west-1b) has
  `AvailableIpAddressCount: 3`.
- **09:52 UTC** - Mitigation: temporarily reduce desired count for lower-priority `cart-svc` and
  `pricing-svc` (freeing ~90 IPs in the shared subnets) and add a spare `/24` subnet,
  `subnet-0c3d4e5f6a7b8c9d0`, to `prod-checkout-svc`'s network configuration.
- **10:05 UTC** - `prod-checkout-svc` reaches 160/160 running tasks.
- **10:12 UTC** - Checkout API 5xx rate on `/api/checkout/submit` returns to the 0.3% baseline.
- **10:30 UTC** - Incident closed after a 15-minute soak with no further placement failures.

## Root Cause

ECS tasks running in `awsvpc` networking mode each require their own elastic network interface (ENI)
and a private IP address from the subnet they launch into. The two production subnets used by
`prod-checkout-svc` were provisioned years earlier as `/26` CIDR blocks (59 usable addresses each
after AWS's 5 reserved addresses) and were shared with `cart-svc` and `pricing-svc`. Their combined
steady-state footprint already consumed the large majority of available addresses, and no IP-address
utilization alerting existed to flag the shrinking headroom as task counts grew over time. When
Application Auto Scaling attempted to add 120 new tasks for the traffic surge, the two subnets had
only about 23 free IP addresses combined, so most new task placements failed at ENI creation and the
service's real capacity was capped far below its desired count of 160.

## Impact

For approximately 50 minutes (09:18-10:12 UTC), `prod-checkout-svc` running capacity was capped at
52-70 tasks against a demand-driven target of 160. Checkout API p99 latency rose from a 380ms
baseline to 4.2s, and the 5xx rate on `/api/checkout/submit` peaked at 9.6%. An estimated 2,300
checkout attempts failed, representing approximately $41,000 in estimated lost transaction value
during the sale window.

## Detection

Detected automatically by the CloudWatch alarm `checkout-svc-DesiredVsRunning-Mismatch` at 09:24 UTC,
9 minutes after scaling began.

## Resolution

1. Reduced desired counts for `cart-svc` and `pricing-svc` to free approximately 90 IP addresses in
   the shared subnets.
2. Added a previously-unused `/24` subnet, `subnet-0c3d4e5f6a7b8c9d0`, to `prod-checkout-svc`'s
   network configuration to provide immediate headroom.
3. Confirmed the service reached 160/160 running tasks by 10:05 UTC and that checkout error rates
   returned to baseline by 10:12 UTC.

## Action Items

1. Migrate `prod-checkout-svc`, `cart-svc`, and `pricing-svc` networking to newly-provisioned `/22`
   subnets (1,000+ usable IPs each). Owner: network-eng, ticket NET-3305.
2. Add a CloudWatch alarm on `AvailableIpAddressCount` falling below 15% of a subnet's total capacity
   for all subnets backing production ECS services.
3. Add a pre-scale-out capacity check that verifies subnet IP headroom before Application Auto
   Scaling executes a large step-scaling action.
4. Document the per-service IP address budget for each shared subnet in the on-call runbook and
   review it quarterly as part of capacity planning.
