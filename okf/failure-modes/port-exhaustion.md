---
type: failure-mode
id: port-exhaustion
name: NAT Gateway per-destination connection ceiling exceeded
services: ["vpc"]
incident_ids: ["INC-2025-1001"]
---

## What it is

A NAT Gateway enforces a hard ceiling on simultaneous connections per unique destination tuple; if every outbound call from a fleet targets the same small set of upstream IPs, scaling that fleet up can concentrate enough concurrent connections on one destination to exceed the ceiling - and the gateway drops the excess silently rather than returning an explicit throttling error, so callers see plain connection timeouts.

## Playbook

[Responding to a NAT Gateway connection ceiling being exceeded](../playbooks/port-exhaustion.md)

## Seen in

- [INC-2025-1001](../../data/raw_rca_docs/synthetic/inc-2025-1001-natgw-port-exhaustion.md) - scaling a payment-worker ASG from 40 to 260 instances, all calling the same handful of payment-gateway IPs through one NAT Gateway, exceeded its 55,000-connections-per-destination limit (see [quota-exhaustion](quota-exhaustion.md)); retries on the resulting timeouts amplified demand further until traffic was spread across two additional AZ-local NAT Gateways.
