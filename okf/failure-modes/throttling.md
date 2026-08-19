---
type: failure-mode
id: throttling
name: Request-rate ceiling exceeded
services: ["api-gateway", "eventbridge", "lambda", "kms"]
incident_ids: ["INC-2025-0601", "INC-2025-0202", "INC-2025-0702", "INC-2025-0302"]
---

## What it is

A request-volume ceiling - an account-level rate limit, a fixed concurrency reservation, or a downstream service's own request-rate quota - gets exceeded and the excess is rejected outright rather than queued or auto-scaled. The ceiling is often sized for steady-state traffic and never revisited as a specific workload's demand grows or spikes.

## Seen in

- [INC-2025-0601](../../data/raw_rca_docs/synthetic/inc-2025-0601-apigw-burst-throttling.md) - API Gateway's account-level throttle (10,000 RPS steady / 5,000-request burst) rejected 38% of requests during a push-notification traffic surge; the campaign's own 12,000 RPS projection had already exceeded the default ceiling three days before a quota increase was requested.
- [INC-2025-0202](../../data/raw_rca_docs/synthetic/inc-2025-0202-lambda-concurrency-throttling.md) - a Lambda's `ReservedConcurrentExecutions` was fixed at 50 during a cost-optimization pass and never revisited; a launch-driven spike exceeded it and every invocation over the ceiling was rejected synchronously, even though the account's unreserved concurrency pool sat mostly idle.
- [INC-2025-0702](../../data/raw_rca_docs/synthetic/inc-2025-0702-dynamodb-missing-gsi.md) - an EventBridge rule misconfigured as `rate(15 minutes)` instead of `rate(1 day)` ran a full-table scan 96x more often than designed, driving read demand against DynamoDB past what auto scaling could keep up with and throttling an unrelated checkout read path sharing the table.
- [INC-2025-0302](../../data/raw_rca_docs/synthetic/inc-2025-0302-s3-replication-lag.md) - S3 cross-region replication's `kms:Decrypt`/`kms:Encrypt` calls exceeded the account's default KMS request-rate quota (5,500 req/s) during a 22-minute ingestion burst; KMS throttled the replication role, backing up replication lag to 4h12m (see [replication-lag](replication-lag.md)).
