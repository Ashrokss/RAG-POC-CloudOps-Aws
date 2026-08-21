---
doc_id: "ed1935ec-3970-43d0-b67d-75f7189b9b87"
incident_id: "INC-2017-0131-GITLAB-DB"
title: "GitLab.com Production PostgreSQL Data Loss from Accidental Directory Removal on Primary"
date: "2017-01-31T23:30:00Z"
severity: critical
services: ["postgresql", "database", "backup", "replication"]
region: "n/a"
account_id: "n/a"
status: "resolved"
tags: ["database", "data-loss", "backup-failure", "replication", "human-error", "public-postmortem"]
source: real
# Extracted by hand from this document's own Impact and Detection sections
# so aggregate questions (longest detection gap, total cost, duration
# ranking) can be answered by sorting a column instead of hoping top-k
# retrieval happens to surface every relevant doc. null = not stated above.
detection_gap_minutes: 0
duration_minutes: 1080
cost_usd: null
---

## Summary

On 31 January 2017, GitLab.com's production PostgreSQL database (db1.cluster.gitlab.com) suffered
permanent data loss after an engineer, while troubleshooting replication lag between the primary
and secondary database, accidentally executed a destructive data-directory removal command against
the primary instead of the secondary. Approximately 300 GB of roughly 310 GB of primary data was
removed before the command was stopped seconds later. Recovery was made significantly harder
because none of the normal recovery mechanisms provided a current, verified restore point: the
secondary was unavailable, `pg_dump` backups had silently been failing (using PostgreSQL 9.2 client
tooling against a 9.6 server), database disk snapshots were not enabled, and the failure-
notification path was ineffective. The only usable recovery point was a manually created LVM
snapshot from approximately six hours earlier, resulting in roughly 6 hours of unrecoverable
database changes and an ~18 hour service outage.

## Timeline

- ~17:20 UTC - A manual LVM snapshot of production is taken for staging purposes - this later
  becomes the only usable restore point.
- ~19:00 UTC - Database load rises, associated with suspected spam and an account-removal
  background job.
- ~21:00 UTC - Database write lockups cause visible downtime.
- ~23:00 UTC - Secondary replication lags; required WAL segments are no longer available on the
  primary. The secondary's data directory is removed to attempt a fresh `pg_basebackup`, which
  cannot connect because the primary lacks available replication connections (`max_wal_senders=3`).
- ~23:00 UTC - `max_wal_senders` is temporarily raised from 3 to 32; the subsequent PostgreSQL
  restart fails due to semaphore exhaustion with `max_connections=8000`, which is then reduced to
  2000 to let PostgreSQL start.
- ~23:30 UTC - `pg_basebackup` still appears to hang. While troubleshooting, the engineer executes
  `rm -rf` against the primary's data directory (db1) intending to target the secondary (db2).
- Seconds later - The engineer notices the mistake and terminates the command, but approximately
  300 GB has already been removed.
- Following hours - Backup and recovery mechanisms are investigated; the `pg_dump`-based backups
  are found to be unusable.
- 1 Feb - GitLab restores service from the ~17:20 UTC LVM snapshot.

## Root Cause

Multiple production terminal sessions were open without a clear, unmistakable indicator of which
host (primary vs. secondary) the active session was connected to, so a directory-removal command
intended for the secondary (db2) was executed against the primary (db1). Recovery then failed
because every independent safety net had a separate, undetected gap at the same time: the secondary
was down, the `pg_dump` backup process used an incompatible PostgreSQL client version (9.2 against a
9.6 server) and had been silently failing, database disk snapshots were not enabled, and the
failure-notification emails were being rejected - so no one was aware backups were not working until
they were needed.

## Impact

- ~300 GB of ~310 GB of primary database data removed.
- ~6 hours of database changes permanently unrecoverable (the gap between the LVM snapshot and the
  deletion).
- GitLab.com unavailable for approximately 18 hours.
- Roughly 5,000 projects, 5,000 comments, and about 700 users affected by the data-loss window.
- Git repositories and wikis, stored separately from the PostgreSQL database, were not affected.

## Detection

The immediate trigger (accidental primary deletion) was noticed by the executing engineer within
one to two seconds and the command was terminated manually - there was no automated detection of
the destructive command itself. The underlying backup failures (`pg_dump` version mismatch,
disabled disk snapshots, broken failure-notification emails) had gone undetected for an extended
prior period because there was no independent monitoring of backup success.

## Resolution

1. The team determined that neither the primary nor the secondary, nor the `pg_dump` backups, could
   provide a current recovery path.
2. The manually created LVM snapshot from ~17:20 UTC was identified as the only usable restore
   point.
3. Production was restored from that snapshot; database sequences were advanced as part of recovery
   to reduce identifier-reuse risk.
4. GitLab.com was gradually re-enabled after restoration and validation, roughly 18 hours after the
   outage began.

## Action Items

- Display hostname, environment, and DB role clearly in every session; require a pre-flight
  identity check before destructive operations.
- Restrict direct destructive filesystem operations; require controlled tooling and peer approval
  for high-impact production commands.
- Pin supported PostgreSQL backup tooling and continuously validate client/server version
  compatibility.
- Monitor backup success independently of email notifications; alert on stale or missing backup
  artifacts.
- Run scheduled restore drills and measure recovery point/time objectives on a regular cadence.
- Assign a dedicated data-durability owner/team responsible for backup health and restore testing.
- Implement continuous WAL archiving/point-in-time recovery alongside multiple independent restore
  mechanisms.
