---
type: failure-mode
id: replication-lag
name: Replication backlog served as if current
services: ["s3"]
incident_ids: ["INC-2025-0302"]
---

## What it is

Cross-region replication for encrypted objects makes a KMS call per object; a write burst large enough to need more decrypt/encrypt throughput than the account's KMS request-rate quota allows gets throttled, and replication lag climbs for as long as the backlog takes to drain - which a downstream cache or read replica may not account for, serving stale data as if it were current.

## Playbook

[Responding to a replication backlog served as current](../playbooks/replication-lag.md)

## Seen in

- [INC-2025-0302](../../data/raw_rca_docs/synthetic/inc-2025-0302-s3-replication-lag.md) - a nightly batch wrote 2.3M objects in a 22-minute burst; the resulting `kms:Decrypt`/`kms:Encrypt` volume exceeded the account's KMS quota (see [throttling](throttling.md)), and replication lag peaked at 4h12m while CloudFront's read origin kept serving stale catalog data as if it were fresh.
