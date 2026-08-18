---
doc_id: "6a7f1666-ce66-4581-8b66-4e0e27ffa087"
incident_id: "INC-2017-0228-S3-USEAST1"
title: "Amazon S3 US-EAST-1 Service Disruption from Oversized Capacity Removal"
date: "2017-02-28T17:37:00Z"
severity: critical
services: ["s3", "ec2", "ebs", "lambda"]
region: "us-east-1"
account_id: "n/a"
status: "resolved"
tags: ["s3", "capacity-management", "input-validation", "cascading-failure", "public-postmortem"]
source: real
# Extracted by hand from this document's own Impact and Detection sections
# so aggregate questions (longest detection gap, total cost, duration
# ranking) can be answered by sorting a column instead of hoping top-k
# retrieval happens to surface every relevant doc. null = not stated above.
detection_gap_minutes: 5
duration_minutes: 257
cost_usd: null
---

## Summary

On February 28, 2017, Amazon S3 in US-EAST-1 became unable to reliably service GET, PUT, LIST, and
DELETE requests for roughly 4 hours 17 minutes (09:37-13:54 PST / 17:37-21:54 UTC), triggered by an
authorized engineer executing a debugging command with a mistyped input parameter during a routine,
pre-approved maintenance playbook intended only to remove a small number of servers from one S3
subsystem. Because a large share of internet infrastructure depends on S3 directly or through
dependent AWS services (EC2, EBS, Lambda), the outage cascaded into visible failures across
numerous high-profile websites and applications, with third-party estimates of financial impact in
the $150M-$160M range.

## Timeline

- 09:37 PST (17:37 UTC) - Engineer executes a debugging command via an established playbook
  intended to remove a small number of servers from one S3 subsystem to address a slow-running
  billing process.
- 09:37-09:39 PST - An incorrectly entered input parameter causes the command to remove a much
  larger number of servers than intended, affecting both the index subsystem and the placement
  subsystem simultaneously.
- 09:40 PST - S3 request error rates spike sharply across US-EAST-1 as remaining capacity is unable
  to serve traffic.
- ~09:45 PST - The public AWS Service Health Dashboard fails to update because it is itself hosted
  on S3 in the affected region; engineers switch to an alternate page and Twitter for status
  updates.
- ~10:00 PST - Root cause (capacity loss in the index and placement subsystems) is identified,
  roughly 20-23 minutes after the triggering command.
- 10:00-13:45 PST - Both subsystems are restarted; because neither had been fully restarted at this
  scale in years, every function and process has to be re-verified as capacity is brought back
  online, consuming most of the recovery time.
- 13:45 PST - S3 object retrieval, storage, and listing operations return to normal.
- ~13:54 PST - All remaining dependent AWS services (e.g. new EC2 instance launches) return to
  normal operation.

## Root Cause

The maintenance tool used to remove servers from the index and placement subsystems had no
lower-bound safeguard: it did not validate the input parameter against a minimum required capacity
before executing the removal. A single mistyped parameter therefore removed far more capacity than
intended from two critical subsystems simultaneously. Recovery was slow because the index and
placement subsystems had not been fully restarted at this scale in several years, so every internal
function and metadata structure had to be verified sequentially as capacity was restored rather
than in parallel - the systems were architected assuming only gradual, small-scale capacity
changes.

## Impact

- Duration: approximately 4 hours 17 minutes of degraded/unavailable service.
- Multiple AWS services depending on S3 for storage - including EC2 instance launches, EBS volumes
  needing snapshots, and Lambda - were degraded or unavailable.
- Numerous high-profile external websites and applications relying on S3 for asset storage
  experienced outages.
- AWS's own public Service Health Dashboard could not display accurate status because the dashboard
  itself depended on the failed service.
- Third-party analysis estimated financial impact across affected businesses at $150M-$160M (not an
  official AWS disclosure).

## Detection

Detected internally within minutes via a sharp, region-wide spike in S3 error rates for PUT, GET,
LIST, and DELETE requests starting at 09:40 PST; some monitoring services observed close to 0%
availability. Root cause was identified approximately 20-23 minutes after the triggering command,
but full recovery took nearly 4 hours because diagnosis speed and recovery speed were bottlenecked
by different constraints.

## Resolution

1. Engineers identified that the index and placement subsystems had lost the bulk of their
   capacity.
2. Both subsystems were fully, sequentially restarted rather than incrementally recovered, since no
   rapid partial-recovery procedure existed for a simultaneous, large-scale capacity loss.
3. Every internal function and metadata structure was re-verified as capacity came back online
   before traffic was considered stable.
4. S3 operations returned to normal at 13:45 PST, with all dependent AWS services normal by 13:54
   PST.

## Action Items

- Modify the removal tool to enforce minimum-capacity safeguards, rejecting any command that would
  drop a subsystem below a safe operating threshold.
- Audit all other operational tools with similar removal/modification capability for the same class
  of missing safeguard.
- Introduce rate-limiting/staged execution so large-scope removal actions apply incrementally
  rather than all at once.
- Re-architect the index and placement subsystems to support partitioned, parallel restart instead
  of a single full-scale sequential restart.
- Rebuild the Service Health Dashboard to run across multiple, independent regions so it stays
  available even if one region's S3 fails.
- Incorporate large-scale, simultaneous capacity-loss scenarios into regular game-day/chaos-
  engineering exercises.
