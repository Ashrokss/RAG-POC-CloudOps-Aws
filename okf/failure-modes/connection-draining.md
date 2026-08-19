---
type: failure-mode
id: connection-draining
name: Deregistration without connection draining
services: ["alb", "ec2"]
incident_ids: ["INC-2025-0401"]
---

## What it is

A target group deregisters an instance immediately on scale-in instead of allowing in-flight requests to finish first, because the deregistration-delay (connection draining) window was left at its unset/zero default rather than an explicit value.

## Seen in

- [INC-2025-0401](../../data/raw_rca_docs/synthetic/inc-2025-0401-ec2-asg-no-connection-draining.md) - a target group's `deregistration_delay.timeout_seconds` was left at 0 by a Terraform module with no explicit default; a routine ASG scale-in terminated 8 instances with zero drain time, cutting 1,140 in-flight requests mid-response over about 6 minutes.
