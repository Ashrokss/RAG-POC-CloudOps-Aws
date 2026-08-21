---
type: failure-mode
id: hot-partition
name: Single partition key absorbing all write traffic
services: ["dynamodb"]
incident_ids: ["INC-2025-0701"]
---

## What it is

All (or nearly all) items in a batch of writes share one partition-key value, so they land on a single physical partition. DynamoDB enforces a per-partition throughput ceiling independent of the table's overall provisioned capacity, and that ceiling can't be raised by adding table-level capacity - only by spreading the same logical write volume across more distinct key values.

## Playbook

[Responding to a single partition-key absorbing all write traffic](../playbooks/hot-partition.md)

## Seen in

- [INC-2025-0701](../../data/raw_rca_docs/synthetic/inc-2025-0701-dynamodb-hot-partition.md) - a 2.4M-record batch import for one tenant used `tenant_id` as the sole partition key; the per-partition 1,000 WCU ceiling was exhausted within two minutes even though the table had 4,000 WCU provisioned overall, and 612,000 records were throttled into a DLQ before the importer was redesigned to write-shard across 10 keys.
