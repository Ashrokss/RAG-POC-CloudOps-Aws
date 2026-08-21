<!--
  Authoring template for RCA (root-cause-analysis) markdown docs ingested by this POC.
  The level-2 (##) section headers below are what rag/ingestion's chunker splits on -
  keep them exactly as named and in this exact order. Renaming, reordering, adding, or
  removing one of these headers will either break section-aware chunking or silently
  misattribute a section's content when building citations.
-->
---
doc_id: ""                       # uuid4 string; leave blank to have ingestion generate one
incident_id: "INC-2026-0001"      # your organization's incident tracking ID
title: "Short, human-readable incident title"
date: "2026-08-14T00:00:00Z"      # UTC ISO-8601 - when the incident occurred, not when this doc was written
severity: critical                # one of: critical | high | medium | low
services: ["service-a", "service-b"]  # AWS services or internal service names affected
region: "us-east-1"                # AWS region where the incident occurred
account_id: "123456789012"         # AWS account ID
status: "resolved"                 # e.g. resolved | mitigated | monitoring
tags: ["networking", "database"]   # free-form labels for filtering/search
source: synthetic                  # one of: real | synthetic
---

## Summary

One or two paragraphs: what happened, at a glance, for someone who will never read past this section.

## Timeline

Chronological, timestamped sequence of events - detection, escalation, mitigation steps, resolution.

## Root Cause

The underlying technical cause. Distinguish the root cause from contributing factors and from the
trigger event that surfaced it.

## Impact

Who and what was affected: customer impact, duration, services degraded, error rates, SLA/SLO breaches.

## Detection

How the incident was detected - alarm, dashboard, customer report - and how long detection took.

## Resolution

What was done to resolve the incident, in the order it was done.

## Action Items

Concrete follow-up items, each with an owner and, ideally, a tracking ticket.
