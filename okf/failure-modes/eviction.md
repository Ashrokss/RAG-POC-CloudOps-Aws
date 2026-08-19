---
type: failure-mode
id: eviction
name: Eviction policy unable to reclaim memory
services: ["elasticache"]
incident_ids: ["INC-2025-0501"]
---

## What it is

A cache eviction policy that only reclaims keys with a TTL (e.g. `volatile-lru`) cannot free memory once a code defect starts writing keys without one; non-expiring keys accumulate until `maxmemory` is reached, at which point the policy has no eligible keys left to evict and new writes are rejected outright rather than triggering eviction.

## Seen in

- [INC-2025-0501](../../data/raw_rca_docs/synthetic/inc-2025-0501-elasticache-eviction-storm.md) - a deploy dropped the `EX` TTL argument from a session-write path; `volatile-lru` could only evict the shrinking pool of TTL-bearing keys, and once `maxmemory` hit 99.7% Redis began rejecting writes with `OOM command not allowed`, cascading into DynamoDB throttling as the app's cache-bypass fallback took over.
