---
doc_id: "0bf82776-629e-41c6-bcdc-cebf6d349e88"
incident_id: "INC-2025-0901"
title: "ECS Fargate Tasks OOMKilled After pandas/numpy Dependency Upgrade"
date: "2025-09-01T09:00:00Z"
severity: high
services: ["ecs", "fargate", "ecr", "sqs"]
region: "us-west-2"
account_id: "719284560033"
status: "resolved"
tags: ["memory", "oom", "fargate", "deployment", "dependencies"]
source: synthetic
# Extracted by hand from this document's own Impact and Detection sections
# so aggregate questions (longest detection gap, total cost, duration
# ranking) can be answered by sorting a column instead of hoping top-k
# retrieval happens to surface every relevant doc. null = not stated above.
detection_gap_minutes: 0
duration_minutes: 190
cost_usd: null
---

## Summary

A routine dependency-upgrade deployment to the `metrics-ingestor-svc` ECS Fargate service raised the
service's steady-state memory footprint from roughly 380 MB to roughly 640 MB per task, while the
task definition's hard memory limit remained 512 MiB. Tasks were repeatedly OOMKilled by the Fargate
kernel, cycling every 5-9 minutes for over an hour before the deployment was rolled back. The metrics
ingestion pipeline fell 1.2 million messages behind and customer-facing metrics dashboards showed
stale data for over three hours.

## Timeline

- **09:00 UTC** - CI/CD pipeline deploys ECS task definition `metrics-ingestor:185` (PR #2291, bumping
  `pandas` 1.5.3 -> 2.1.1 and `numpy` 1.24.4 -> 1.26.0) to `prod-data-cluster` via a rolling update.
- **09:14 UTC** - First task OOMKilled; CloudWatch Container Insights alarm
  `metrics-ingestor-MemoryUtilization-High` (threshold: `MemoryUtilization > 90%` for 3 datapoints)
  fires.
- **09:20 UTC** - ECS scheduler restarts the task; a second task is OOMKilled within 6 minutes of
  startup, well before steady load would normally be reached.
- **09:35 UTC** - On-call SRE paged after 12 tasks OOMKilled within 20 minutes; error-budget burn
  alarm for the metrics pipeline also fires.
- **09:48 UTC** - `aws ecs describe-tasks` shows `stoppedReason: "OutOfMemoryError: Container killed
  due to memory usage"` and container exit code `137` on every recent task.
- **10:05 UTC** - Engineer correlates the OOM onset with the 09:00 UTC deployment and diffs the task
  definition revisions, identifying the `pandas`/`numpy` version bump in PR #2291.
- **10:15 UTC** - Mitigation: `aws ecs update-service --cluster prod-data-cluster --service
  metrics-ingestor-svc --task-definition metrics-ingestor:184` rolls back to the prior image.
- **10:29 UTC** - Service reaches steady state; `MemoryUtilization` returns to its ~60% baseline.
- **12:45 UTC** - SQS queue `metrics-ingest-queue` backlog (peaked at 1.2M messages) fully drains;
  incident closed.

## Root Cause

`pandas` 2.1.1 defaults to a PyArrow-backed string storage representation for object/string columns,
which for this service's ingestion workload - wide Parquet files pulled from S3 with mostly string
columns - increased per-DataFrame memory overhead by roughly 1.7x compared to `pandas` 1.5.3. The
concurrent `numpy` 1.26.0 upgrade also changed default buffer copy behavior, further increasing
retained memory during transform steps. Neither change was caught by existing tests because none of
them asserted on memory usage. The task definition's hard memory limit was left at 512 MiB, a value
sized for the pre-upgrade footprint, so the new steady-state RSS of ~640 MB consistently exceeded the
container's cgroup limit under normal (not even peak) ingestion load. The Fargate microVM's kernel
OOM killer terminated the container process each time, which ECS reported back as exit code 137 and
`stoppedReason: "OutOfMemoryError: Container killed due to memory usage."` The trigger was the
dependency bump; the root cause was deploying a materially higher memory footprint without
re-validating or adjusting the task's memory allocation.

## Impact

`metrics-ingestor-svc` tasks cycled roughly every 5-9 minutes between 09:14 and 10:29 UTC (75
minutes), with the service's effective throughput reduced by approximately 70%. The upstream SQS
queue `metrics-ingest-queue` backlog grew to 1.2 million messages. Downstream customer-facing metrics
dashboards breached their 15-minute freshness SLA for 3 hours 10 minutes across roughly 180 customer
accounts before the backlog fully drained.

## Detection

Detected automatically via the CloudWatch Container Insights alarm
`metrics-ingestor-MemoryUtilization-High` at 09:14 UTC, 14 minutes after the deployment began.

## Resolution

1. Rolled back the ECS service to task definition revision `metrics-ingestor:184` at 10:15 UTC.
2. Confirmed steady state and normal memory utilization by 10:29 UTC.
3. Monitored SQS backlog drain, confirming full recovery by 12:45 UTC.
4. Follow-up fix merged separately: pinned task memory to 1024 MiB and re-enabled the pandas/numpy
   upgrade with `pd.options.future.infer_string = False` to avoid the PyArrow-backed string overhead.

## Action Items

1. Permanently raise `metrics-ingestor` Fargate task memory from 512 MiB to 1024 MiB and re-baseline
   the `MemoryUtilization` alarm thresholds. Owner: data-platform, ticket DATA-4821.
2. Add a memory-regression gate to the dependency-upgrade CI pipeline that fails the build if
   steady-state RSS grows more than 15% versus the previous release.
3. Enable the ECS deployment circuit breaker with automatic rollback for `metrics-ingestor-svc` so
   future regressions revert without paging on-call.
4. Add a CloudWatch alarm on `metrics-ingest-queue` `ApproximateNumberOfMessagesVisible` to surface
   backlog growth earlier and independently of task health.
