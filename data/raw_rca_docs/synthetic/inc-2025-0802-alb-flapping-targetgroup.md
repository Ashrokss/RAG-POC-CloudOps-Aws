---
doc_id: "4c51612d-46bc-42b1-a6f0-faa18404fd2a"
incident_id: "INC-2025-0802"
title: "CloudFront Origin 5xx Spike from Flapping ALB Target-Group Health Checks"
date: "2025-08-02T14:02:00Z"
severity: high
services: ["cloudfront", "alb", "ecs"]
region: "us-east-1"
account_id: "482910735620"
status: "resolved"
tags: ["networking", "load-balancer", "health-check", "5xx", "cloudfront"]
source: synthetic
---

## Summary

A routine canary deployment of `prod-web-service` (v2.38.0) to ECS Fargate on 2025-08-02 triggered a
feedback loop in which ALB target-group health checks began failing intermittently, causing the
target group `prod-web-tg` to lose healthy capacity in waves. As targets deregistered, the ALB
`prod-web-alb` began returning `502 Bad Gateway` for requests with no healthy backend, and CloudFront
propagated these as origin 5xx errors to end users. The 5xx error rate peaked at 22% for roughly 18
minutes before the deployment was rolled back and the target group stabilized.

## Timeline

- **14:02 UTC** - Deployment of task definition `prod-web:v2.38.0` begins rolling out to the
  `prod-web-service` ECS service (12 desired tasks).
- **14:14 UTC** - CloudWatch alarm `prod-web-tg-UnhealthyHostCount-High` fires (threshold:
  `UnhealthyHostCount >= 3` for 2 consecutive 1-minute periods) on target group
  `arn:aws:elasticloadbalancing:us-east-1:482910735620:targetgroup/prod-web-tg/1a2b3c4d5e6f7a8b`.
- **14:16 UTC** - PagerDuty pages the on-call SRE.
- **14:19 UTC** - On-call confirms `HTTPCode_ELB_5XX_Count` has spiked to 14,200 over 10 minutes and
  that CloudFront distribution `E1A2B3C4D5E6F7` is serving `502 Bad Gateway` with
  `X-Cache: Error from cloudfront` on an increasing share of requests.
- **14:27 UTC** - ALB access logs show repeated entries with `target_status_code "-"` and
  `error_reason "Target.FailedHealthChecks"`; healthy host count is oscillating between 4 and 11 of 12
  every 90-150 seconds.
- **14:35 UTC** - ECS task logs for the new revision show JVM full-GC pauses of 700ms-1.2s under load;
  correlated with health-check timeouts on `/healthz`.
- **14:41 UTC** - On-call rolls back the ECS service to task definition `prod-web:v2.37.4`.
- **14:53 UTC** - `HealthyHostCount` for `prod-web-tg` recovers to 12/12 and holds steady.
- **15:05 UTC** - CloudFront 5xx error rate returns to baseline (<0.1%); incident declared resolved
  after a 15-minute soak.

## Root Cause

The `/healthz` endpoint executed a synchronous `SELECT 1` against RDS through the application's
connection pool on every health check. Task definition revision `v2.38.0` reduced the Fargate
container memory limit from 2048 MiB to 1024 MiB but left the JVM heap flag at `-Xmx1536m`
unchanged, leaving no headroom between heap and container cgroup limit. Under normal request load
this caused frequent full garbage-collection pauses of 700ms-1.2s. The ALB health check
(`/healthz`, 5s timeout, 10s interval, unhealthy threshold 2) occasionally observed response times
pushed past the timeout during a GC pause, causing the ALB to mark that target unhealthy and
deregister it. Removing capacity increased load on the remaining targets, which increased GC
pressure on them in turn - a self-reinforcing feedback loop that caused targets to flap in and out of
service roughly every 90-150 seconds. Whenever all targets were simultaneously unhealthy, the ALB
had no backend to route to and returned `502 Bad Gateway`, which CloudFront relayed to clients as an
origin 5xx error. The trigger was the deploy; the root cause was the unchanged heap flag combined
with a DB-coupled health check that was itself vulnerable to the same GC-induced latency it was
supposed to detect.

## Impact

CloudFront 5xx error rate peaked at 22% for approximately 18 minutes (14:19-14:37 UTC) and remained
elevated above 2% for a total of 39 minutes. An estimated 61,000 client requests received a 5xx
response. No data loss occurred; this was an availability/latency incident only.

## Detection

Detected automatically by the CloudWatch alarm `prod-web-tg-UnhealthyHostCount-High` at 14:14 UTC,
12 minutes after the deployment began and roughly 5 minutes after the first customer-visible errors.

## Resolution

1. Rolled back `prod-web-service` to task definition `prod-web:v2.37.4` at 14:41 UTC.
2. Confirmed `HealthyHostCount` returned to 12/12 by 14:53 UTC.
3. Confirmed CloudFront 5xx rate returned to baseline by 15:05 UTC and closed the incident after a
   15-minute soak period.

## Action Items

1. Remove the RDS dependency from `/healthz`; add a separate `/readyz` for dependency checks that is
   not used by the ALB target-group health check. Owner: web-platform team, ticket WEB-2214.
2. Add a CI check that fails the build if a task definition's JVM `-Xmx` value leaves less than 25%
   headroom below the container memory limit. Owner: platform-eng, PLAT-1177.
3. Increase `prod-web-tg` unhealthy threshold from 2 to 5 consecutive failures and add a 30-second
   deregistration delay to reduce sensitivity to transient latency spikes.
4. Add an automated deployment gate that halts and rolls back a rollout if `HTTPCode_ELB_5XX_Count`
   exceeds 1% of requests during the first 10 minutes of a deploy.
