---
type: failure-mode
id: oom
name: Memory limit exceeded under normal load
services: ["ecs"]
incident_ids: ["INC-2025-0901"]
---

## What it is

A container's hard memory limit was sized for a workload's memory footprint at one point in time; a change that raises steady-state memory usage - a dependency upgrade, a new code path - without a corresponding review of that limit causes the container to be OOM-killed under normal, not even peak, load.

## Seen in

- [INC-2025-0901](../../data/raw_rca_docs/synthetic/inc-2025-0901-ecs-oomkilled.md) - a `pandas`/`numpy` upgrade raised a service's steady-state memory footprint from ~380MB to ~640MB against an unchanged 512MiB task memory limit (see [config-regression](config-regression.md)); tasks were OOMKilled every 5-9 minutes for over an hour, backing up 1.2M messages in the upstream queue (see [backlog](backlog.md)).
