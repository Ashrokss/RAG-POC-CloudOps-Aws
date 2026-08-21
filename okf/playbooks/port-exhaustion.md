---
type: playbook
id: port-exhaustion
name: Responding to a NAT Gateway connection ceiling being exceeded
failure_mode: port-exhaustion
services: ["vpc"]
owned_by: "TBD - set in review"
---

## When you see this

An `ErrorPortAllocation` alarm, and/or outbound connection timeouts or `EADDRNOTAVAIL` errors with no explicit throttling response from the destination service itself.

## Mitigate

1. Confirm via the NAT Gateway's `ErrorPortAllocation` metric that port allocation - not the destination service - is the actual bottleneck.
2. Scale down the fleet driving the connection burst if possible, and cap per-instance outbound connection concurrency.
3. Provision additional AZ-local NAT Gateways so outbound traffic isn't concentrated through a single gateway, and repoint route tables accordingly.

## Prevent

- Add persistent connection pooling / keep-alive reuse to reduce the connections-per-call ratio against fixed-IP destinations.
- Make one-NAT-Gateway-per-AZ, with AZ-affine route tables, the permanent topology rather than a single shared gateway.
- Add a pre-scale-out guardrail capping fleet size relative to the known NAT Gateway connection budget.
- Add a composite alarm combining `ErrorPortAllocation` with packet-drop metrics for earlier warning before errors become customer-visible.

## Related

- Failure mode: [NAT Gateway per-destination connection ceiling exceeded](../failure-modes/port-exhaustion.md)
- Incidents: INC-2025-1001
