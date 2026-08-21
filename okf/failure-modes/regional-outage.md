---
type: failure-mode
id: regional-outage
name: Provider-side regional capacity loss
services: ["ebs", "s3"]
incident_ids: ["INC-2017-0228-S3-USEAST1"]
---

## What it is

A provider-side capacity or availability loss in one region cascades into every service that depends on it, including services in the same provider's own stack - and recovery can be slower than the outage's onset if the affected subsystem hasn't been restarted at that scale in years, forcing a sequential rather than parallel recovery.

## Playbook

[Responding to a provider-side regional capacity loss](../playbooks/regional-outage.md)

## Seen in

- [INC-2017-0228-S3-USEAST1](../../data/raw_rca_docs/real/inc-2017-0228-s3-useast1-outage.md) - an operator command with an unvalidated input parameter removed far more capacity than intended from two S3 subsystems simultaneously; because neither had been fully restarted at that scale in years, every function had to be re-verified sequentially during recovery, extending a ~20-minute diagnosis into a 4h17m outage that took down EC2 launches, EBS snapshots, and Lambda alongside S3 itself.
