---
doc_id: "61a6d661-a53d-4002-a8a9-96f1694f3726"
incident_id: "INC-2025-1001"
title: "NAT Gateway Port Allocation Exhaustion Blocks Outbound Payment API Calls"
date: "2025-10-01T03:10:00Z"
severity: critical
services: ["nat-gateway", "vpc", "ec2"]
region: "us-east-1"
account_id: "837120945566"
status: "resolved"
tags: ["networking", "nat-gateway", "connection-exhaustion", "capacity", "payments"]
source: synthetic
# Extracted by hand from this document's own Impact and Detection sections
# so aggregate questions (longest detection gap, total cost, duration
# ranking) can be answered by sorting a column instead of hoping top-k
# retrieval happens to surface every relevant doc. null = not stated above.
detection_gap_minutes: 19
duration_minutes: 115
cost_usd: 12500
---

## Summary

A backlog-clearing batch job scaled the `payment-worker-asg` Auto Scaling group from 40 to 260
instances, all routing outbound HTTPS calls to a third-party payment gateway through a single NAT
Gateway, `nat-0f4e6d8c2b1a3f5e7`. Because the gateway resolved to a small, fixed set of upstream IPs,
concurrent connections to those destinations exceeded the NAT Gateway's 55,000-simultaneous
connections-per-destination limit. The NAT Gateway began silently dropping new connection attempts,
which surfaced to callers as timeouts and address-allocation errors rather than an explicit
throttling response, and retry logic amplified the problem. Payment API call failures peaked at 61%
for nearly two hours.

## Timeline

- **03:10 UTC** - A nightly reconciliation job triggers an Auto Scaling scale-out of
  `payment-worker-asg` from 40 to 260 instances to clear a backlog of 1.8 million pending
  transactions.
- **03:22 UTC** - Worker instances begin logging elevated error rates calling
  `api.paymentgw.example.com`, including `Error: connect ETIMEDOUT 52.94.xxx.xxx:443` and
  `Error: connect EADDRNOTAVAIL`; built-in retry logic increases connection attempt volume further.
- **03:29 UTC** - CloudWatch alarm `nat-gw-ErrorPortAllocation-High`
  (`ErrorPortAllocation > 0` for 3 consecutive periods) fires on `nat-0f4e6d8c2b1a3f5e7`.
- **03:34 UTC** - On-call SRE paged; the payment success-rate dashboard shows a 61% timeout/5xx rate
  on outbound calls to the payment gateway.
- **03:47 UTC** - Investigation confirms all private-subnet outbound traffic routes through the single
  NAT Gateway `nat-0f4e6d8c2b1a3f5e7`, and its `ErrorPortAllocation` metric shows 148,000 failed port
  allocations over the preceding 10 minutes.
- **03:58 UTC** - Mitigation #1: scale `payment-worker-asg` back down to 80 instances and cap
  per-instance outbound connection concurrency to 50 via application config.
- **04:10 UTC** - Mitigation #2: provision two additional NAT Gateways, `nat-0aa1bb2cc3dd4ee5f` and
  `nat-0bb2cc3dd4ee5ff60`, in the other two AZ subnets, and update route tables so each AZ's private
  subnets egress through their own AZ-local NAT Gateway.
- **04:35 UTC** - `ErrorPortAllocation` drops to 0 across all three NAT Gateways; payment API success
  rate recovers to 99.4%.
- **05:05 UTC** - Transaction backlog fully drained; incident closed.

## Root Cause

A NAT Gateway enforces a hard limit of 55,000 simultaneous connections per unique destination
(protocol, destination IP, destination port) tuple. Because `api.paymentgw.example.com` resolved to
only a handful of fixed upstream IP addresses, every outbound connection from every private subnet -
funneled through the single NAT Gateway `nat-0f4e6d8c2b1a3f5e7` - concentrated on the same small set
of destination 5-tuples. When the reconciliation job scaled the worker fleet 6.5x, aggregate
concurrent connections to those destinations exceeded the 55,000-connection ceiling. The NAT Gateway
does not return an explicit throttling error when its port allocation table for a destination is
full; it drops the new connection attempt, which callers observe as a connection timeout or
`EADDRNOTAVAIL`. Because each worker opened a new TCP+TLS connection per API call rather than reusing
persistent connections, and retry logic re-attempted failed calls immediately, connection demand
further outstripped the available port allocation capacity, deepening the outage.

## Impact

Outbound payment API call failures peaked at 61% and remained elevated for approximately 1 hour 55
minutes (03:10-05:05 UTC). Approximately 340,000 transactions were delayed (none were lost; all were
eventually reconciled), causing a same-day settlement SLA breach for 3 merchant partners and an
estimated $12,500 in contractual SLA credits.

## Detection

Detected automatically via the CloudWatch alarm `nat-gw-ErrorPortAllocation-High` at 03:29 UTC, 19
minutes after the scale-out began and 7 minutes after the first elevated error logs appeared.

## Resolution

1. Scaled `payment-worker-asg` down from 260 to 80 instances and capped per-instance outbound
   connection concurrency.
2. Provisioned two additional AZ-local NAT Gateways and repointed route tables so outbound traffic no
   longer concentrated on a single NAT Gateway.
3. Confirmed `ErrorPortAllocation` returned to 0 and payment success rate recovered to 99.4% by 04:35
   UTC, then monitored backlog drain to completion by 05:05 UTC.

## Action Items

1. Make the one-NAT-Gateway-per-AZ topology with AZ-affine route tables permanent across all VPCs
   hosting payment-worker infrastructure. Owner: network-eng, ticket NET-3350.
2. Add persistent HTTP connection pooling and keep-alive reuse to the payment-worker HTTP client to
   reduce the connections-per-transaction ratio.
3. Add a pre-scale-out guardrail in the Auto Scaling policy that caps maximum fleet size relative to
   the known NAT Gateway per-destination connection budget, and evaluate migrating the payment
   gateway integration to a vendor-provided PrivateLink endpoint.
4. Add a composite CloudWatch alarm combining `ErrorPortAllocation` and `PacketsDropCount` to provide
   earlier warning before errors become customer-visible.
