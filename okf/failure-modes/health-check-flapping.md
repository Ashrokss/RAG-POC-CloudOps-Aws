---
type: failure-mode
id: health-check-flapping
name: Health check flapping under a self-reinforcing loop
services: ["alb", "ec2", "ecs"]
incident_ids: ["INC-2025-0402", "INC-2025-0802"]
---

## What it is

A health check starts failing intermittently for a reason unrelated to real request-serving capacity - a startup-time regression outrunning the grace period, or GC pauses pushing response time past the check's own timeout - so the orchestrator (an ASG or a target group) replaces or deregisters targets that were actually fine. Removing capacity increases load on what's left, which can make the same check fail on the survivors too, so the loop can be self-sustaining rather than self-correcting.

## Seen in

- [INC-2025-0402](../../data/raw_rca_docs/synthetic/inc-2025-0402-ec2-asg-flapping-healthcheck.md) - a deploy added a synchronous cache-warming step that tripled a service's startup time (20s to 90s), but the ASG's `HealthCheckGracePeriod` stayed at 30s; new instances were marked unhealthy before they finished starting, and each replacement hit the same grace period, cycling through 46 replacements over 118 minutes.
- [INC-2025-0802](../../data/raw_rca_docs/synthetic/inc-2025-0802-alb-flapping-targetgroup.md) - a task definition reduced the Fargate memory limit without lowering the JVM `-Xmx` flag to match, causing GC pauses of 700ms-1.2s; the ALB health check's 5s timeout occasionally landed during a pause, deregistering healthy targets and increasing GC pressure on the rest - flapping roughly every 90-150 seconds until all targets were unhealthy simultaneously and the ALB returned 502.
