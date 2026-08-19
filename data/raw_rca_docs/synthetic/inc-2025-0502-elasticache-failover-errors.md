---
doc_id: "7761f1cb-19bd-4cf3-b9c9-6548de597742"
incident_id: "INC-2025-0502"
title: "ElastiCache Redis Failover During Maintenance Window Caused Brief Write Errors"
date: "2025-05-18T05:12:00Z"
severity: medium
services: ["ElastiCache for Redis", "ECS"]
region: "us-east-1"
account_id: "855103427491"
status: "resolved"
tags: ["elasticache", "redis", "failover", "maintenance-window", "client-retry"]
source: synthetic
---

## Summary

During the replication group `orders-cache-prod`'s scheduled maintenance window (`sun:05:00-sun:06:00 UTC`), AWS applied an engine-version patch (Redis 7.0.7 to 7.1.0) to the primary node, triggering an automatic failover that promoted replica `orders-cache-prod-002` to primary. The failover itself completed in 19 seconds, but the `orders-service` ECS tasks used a `redis-py` connection pool with no `retry_on_timeout` and no backoff configured, and DNS resolution for the cluster's primary endpoint had a 30-second TTL. For roughly 42 seconds, some clients continued sending writes to the old primary's cached IP and received `redis.exceptions.ConnectionError: Error 111 connecting to orders-cache-prod.xxxxx.0001.use1.cache.amazonaws.com:6379. Connection refused.`, while others resolved the new primary but briefly hit the old one still in `READONLY` mode, receiving `READONLY You can't write against a read only replica.` 2,140 write operations failed, surfacing as HTTP 500 to 312 checkout attempts before client retries succeeded.

## Timeline

- 2025-05-18T05:00:00Z - Scheduled maintenance window for `orders-cache-prod` opens; AWS begins applying the Redis 7.0.7 -> 7.1.0 engine patch to the primary node `orders-cache-prod-001`.
- 2025-05-18T05:12:03Z - AWS initiates automatic failover, promoting replica `orders-cache-prod-002` to primary. EventBridge emits an ElastiCache "Replication group failover" event.
- 2025-05-18T05:12:22Z - Failover completes (19 seconds); the cluster's primary endpoint DNS record is updated to point at `orders-cache-prod-002`.
- 2025-05-18T05:12:25Z - CloudWatch alarm `orders-cache-WriteErrors` fires as `orders-service` ECS tasks begin logging `redis.exceptions.ConnectionError: Error 111 connecting to orders-cache-prod.xxxxx.0001.use1.cache.amazonaws.com:6379. Connection refused.`; some tasks also log `READONLY You can't write against a read only replica.` PagerDuty pages on-call.
- 2025-05-18T05:13:05Z - Stale DNS cache entries (30-second TTL) expire across ECS tasks; new connections resolve to `orders-cache-prod-002` and write errors stop. Total error window: 42 seconds.
- 2025-05-18T05:16:00Z - On-call confirms via the ElastiCache console that failover was an expected, AWS-initiated event tied to the maintenance window and engine version is now `7.1.0` on both nodes.
- 2025-05-18T05:24:00Z - On-call reviews `orders-service` retry metrics and confirms all 2,140 failed writes were eventually retried successfully by the application's outer HTTP retry layer, except for 312 requests that had already exhausted their retry budget and returned `500` to the client.
- 2025-05-18T05:40:00Z - Incident closed; no further errors observed over a 30-minute monitoring period.

## Root Cause

The root cause was that the `orders-service` Redis client configuration had no `retry_on_timeout` or exponential backoff on connection errors, and relied on DNS TTL expiry (30 seconds) rather than ElastiCache's cluster-mode-aware endpoint resolution to discover the new primary after a failover. The AWS-initiated maintenance patch and resulting automatic failover were an expected, routine trigger, not a fault; the gap was that the client library treated a transient, self-healing 19-second topology change as a hard failure instead of retrying, so requests issued during the DNS propagation window failed outright rather than transparently succeeding on retry.

## Impact

2,140 write operations (session and order-state cache writes) failed between 05:12:25 and 05:13:05 UTC. 1,828 were retried successfully by the application's HTTP-level retry logic; 312 checkout requests had already exhausted their retry budget and returned `HTTP 500` to the client, an estimated 0.8% of order-writes in that minute. No data was lost or corrupted; DynamoDB remained the durable order store throughout.

## Detection

Detected by CloudWatch alarm `orders-cache-WriteErrors` (threshold: error log pattern match rate `> 20/minute`), which fired 2 seconds after the first connection error, and corroborated by the EventBridge failover notification for `orders-cache-prod`.

## Resolution

1. Confirmed the failover was AWS-initiated maintenance and had already self-resolved by the time on-call engaged.
2. Verified engine version `7.1.0` was correctly applied to both the new primary and the replica.
3. Reviewed and confirmed the application's outer retry layer had absorbed the majority of failures without customer-visible impact.
4. Manually notified the 312 affected checkout sessions' owning team so support could proactively reach out if customers reported failed orders.

## Action Items

- Add `retry_on_timeout=True` and exponential backoff (base 100ms, max 3 retries) to the shared Redis client wrapper used by `orders-service` and audit other services for the same gap. Owner: platform-caching-team, JIRA-6410.
- Subscribe an SNS topic to ElastiCache maintenance and failover events so on-call gets proactive notice before, not just during, a scheduled patch window. Owner: observability-team, JIRA-6411.
- Evaluate moving `orders-cache-prod` to cluster-mode enabled with a configuration endpoint, which resolves topology changes without relying on DNS TTL expiry. Owner: platform-caching-team, JIRA-6412.
- Run a quarterly failover game-day against a non-production replica to validate client retry behavior. Owner: sre-team, JIRA-6413.
