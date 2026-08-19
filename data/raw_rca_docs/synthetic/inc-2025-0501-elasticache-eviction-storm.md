---
doc_id: "b61f30fb-81d0-4922-8041-8be5f4ad7eea"
incident_id: "INC-2025-0501"
title: "Missing Session-Key TTLs Triggered a Redis Eviction Storm and Cache Stampede"
date: "2025-05-05T08:47:00Z"
severity: critical
services: ["ElastiCache for Redis", "DynamoDB", "API Gateway"]
region: "eu-west-1"
account_id: "855103427491"
status: "resolved"
tags: ["elasticache", "redis", "cache-stampede", "memory-eviction", "dynamodb-throttling"]
source: synthetic
---

## Summary

`session-service` v2.14.0, deployed the previous evening, introduced a code path that wrote session keys with a plain `SET session:{id} {payload}` call instead of `SET session:{id} {payload} EX 3600`, leaving new sessions without a TTL. Over the following hours these un-expiring keys filled the `sessions-redis-001` replication group (node type `cache.r6g.xlarge`, 13.07 GB per node) to 99.7% of `maxmemory`. Because the cluster's `maxmemory-policy` was `volatile-lru`, which only evicts keys that have a TTL, Redis could not free space and began rejecting writes with `OOM command not allowed when used memory > 'maxmemory'.` The application's fallback path then read/wrote session data directly against DynamoDB table `user-sessions`, and the resulting cache-bypass stampede drove DynamoDB into throttling with `ProvisionedThroughputExceededException`. Login and session-refresh endpoints degraded for 47 minutes.

## Timeline

- 2025-05-04T21:00:00Z - `session-service` v2.14.0 deployed to production; new session-write path omits the `EX` TTL argument.
- 2025-05-05T08:31:00Z - CloudWatch alarm `sessions-redis-DatabaseMemoryUsagePercentage-High` fires at 91% used memory on `sessions-redis-001`.
- 2025-05-05T08:40:00Z - `Evictions` metric on `sessions-redis-001` spikes to 340,000/minute as `volatile-lru` scrambles to reclaim space from the shrinking pool of TTL-bearing keys.
- 2025-05-05T08:47:00Z - Memory hits 13.03 GB of 13.07 GB (99.7%); writes begin failing with `OOM command not allowed when used memory > 'maxmemory'.`; `/login` endpoint error rate climbs to 61%. PagerDuty pages on-call.
- 2025-05-05T08:52:00Z - DynamoDB table `user-sessions` (provisioned 4,000 RCU / 4,000 WCU) starts returning `ProvisionedThroughputExceededException` as the app's fallback path bypasses the now-unusable cache; 18,200 throttled requests recorded over the next 10 minutes.
- 2025-05-05T08:58:00Z - On-call identifies the missing-TTL write path via `redis-cli --bigkeys` sampling, finding session keys with `TTL -1` (no expiry) making up 94% of keyspace.
- 2025-05-05T09:04:00Z - On-call rolls back `session-service` to v2.13.2 and sets `maxmemory-policy` to `allkeys-lru` as an immediate stopgap so all keys become evictable.
- 2025-05-05T09:34:00Z - Memory usage stabilizes at 68%, evictions return to near zero, DynamoDB throttling clears. Incident closed.

## Root Cause

The root cause was a code defect in `session-service` v2.14.0 that wrote session keys without an expiry, combined with a `maxmemory-policy` of `volatile-lru` that cannot evict keys lacking a TTL. As non-expiring keys accumulated, they permanently occupied memory that would normally cycle out, and once `maxmemory` was reached the policy had no eligible keys left to evict fast enough, causing write rejections. The deploy is the trigger; the interaction between a TTL-less write path and a TTL-only eviction policy is the root cause of the memory exhaustion. The DynamoDB throttling was a secondary, cascading effect: the application's cache-miss fallback logic had no circuit breaker, so every failed Redis write turned into a direct DynamoDB call, multiplying load on the table well beyond its provisioned throughput.

## Impact

Login success rate dropped to 39% (61% error rate) for 47 minutes (08:47-09:34 UTC), affecting an estimated 22,000 login attempts. 18,200 DynamoDB requests were throttled, adding retry latency of 2-6 seconds to affected requests. No session data was lost; DynamoDB remained the durable source of truth throughout.

## Detection

Detected by CloudWatch alarm `sessions-redis-DatabaseMemoryUsagePercentage-High` (threshold `> 90%`), which fired 16 minutes before memory exhaustion became write-impacting, giving partial but insufficient lead time to intervene before user-facing errors began.

## Resolution

1. Rolled back `session-service` to v2.13.2 to stop new TTL-less writes.
2. Set `maxmemory-policy` to `allkeys-lru` on `sessions-redis-001` as an immediate stopgap to make all keys evictable.
3. Ran a `SCAN`-based cleanup script to explicitly delete keys matching `session:*` with `TTL -1` older than 24 hours.
4. Monitored `DatabaseMemoryUsagePercentage` and DynamoDB `ThrottledRequests` until both returned to baseline.

## Action Items

- Add a pre-deploy CI check that rejects any Redis `SET` call in the session-write path lacking an explicit expiry. Owner: session-team, JIRA-6301.
- Keep `maxmemory-policy` at `allkeys-lru` permanently rather than reverting to `volatile-lru`, following a review of any code that relies on non-expiring keys. Owner: platform-caching-team, JIRA-6302.
- Add a circuit breaker around the DynamoDB fallback path so a cache outage degrades gracefully instead of forwarding full load to the table. Owner: session-team, JIRA-6303.
- Add a dashboard panel for percentage of keys without a TTL per cluster, alerting above 5%. Owner: observability-team, JIRA-6304.
