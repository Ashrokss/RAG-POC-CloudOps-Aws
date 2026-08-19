---
doc_id: "38a80fbd-ef61-426f-ae6e-a19cf9834cf3"
incident_id: "INC-2023-1102-CF-CONTROLPLANE"
title: "Cloudflare Control Plane and Analytics Outage from PDX-04 Total Power Loss"
date: "2023-11-02T11:43:00Z"
severity: critical
services: ["control-plane", "dashboard", "api", "analytics", "logging", "kafka", "clickhouse"]
region: "hillsboro-or"
account_id: "n/a"
status: "resolved"
tags: ["control-plane", "data-center-power-failure", "disaster-recovery", "single-facility-dependency", "public-postmortem"]
source: real
---

## Summary

Cloudflare's control plane (dashboard, APIs) and analytics/logging pipeline were degraded or
unavailable for approximately 40.5 hours (2-4 November 2023) after Flexential's PDX-04 data center
in Hillsboro, Oregon lost its utility power feed, then its backup generators and UPS batteries in
rapid succession following a ground fault - a near-total, near-simultaneous loss of every power
source serving the site. Cloudflare's edge network (CDN, WAF, DDoS mitigation, DNS resolution for
customer traffic) continued operating normally throughout; only the control plane and
analytics/logging, which depended on PDX-04, were affected.

## Timeline

- 2 Nov, 08:50 UTC - PGE performs unplanned maintenance on one of two utility feeds into PDX-04;
  Flexential fails over to generators without informing Cloudflare.
- 2 Nov, ~11:40 UTC - A ground fault on a PGE transformer triggers a protective shutdown that also
  takes all 10 of PDX-04's generators offline - both utility and generator power lost
  simultaneously.
- 2 Nov, 11:40-11:44 UTC - PDX-04 runs on UPS batteries rated for ~10 minutes; they begin failing
  after only ~4 minutes.
- 2 Nov, 11:44 UTC - The two routers connecting PDX-04 to the outside world go offline - Cloudflare's
  first internal signal of a problem.
- 2 Nov, 12:28 UTC - Flexential sends its first message confirming a power issue, ~44 minutes after
  the routers dropped.
- 2 Nov, 13:40 UTC - With no ETA from Flexential, Cloudflare decides to fail over control plane
  services to its disaster-recovery sites in Europe.
- 2 Nov, 13:43 UTC - First services come online at the EU DR site; a thundering-herd of retried API
  calls overwhelms services, requiring emergency rate limiting.
- 2 Nov, 17:57 UTC - Services on the DR site stabilize; most customers regain dashboard/API access.
- 2 Nov, 22:48 UTC - Flexential finishes replacing faulty circuit breakers and restores clean power
  to PDX-04.
- 4 Nov, 04:25 UTC - All services fully restored after a full cold-boot rebuild of PDX-04.

## Root Cause

Recovery took roughly 40 hours because of three compounding factors: (1) Flexential did not
proactively inform Cloudflare when it switched to generator power at 08:50 UTC, delaying awareness
of the facility's degraded state; (2) faulty circuit breakers blocked fast power restoration once
generators were back online; and (3) a subset of "high availability" control-plane services - most
critically the Kafka and ClickHouse logging/analytics cluster - had an undisclosed, single-facility
dependency on PDX-04 that was never tested, so the two healthy core data centers could not fully
absorb the failure the way the active-active HA design intended.

## Impact

- Services affected: Cloudflare dashboard, most APIs, logging, analytics, and select newer products
  with incomplete DR coverage (Stream video uploads, some Magic WAN configuration).
- Services NOT affected: Cloudflare's global edge network (CDN, WAF, DDoS mitigation, DNS
  resolution).
- Duration: ~40.5 hours total; most severe control-plane impact lasted ~6 hours 14 minutes before DR
  failover stabilized most services.
- Data impact: most analytics unaffected long-term due to EU replication; some non-EU-replicated
  datasets and Logpush data for the outage window were permanently lost.

## Detection

Detected internally at 11:44 UTC when the two routers connecting PDX-04 to the outside world went
offline - Cloudflare's own network monitoring, not the data center provider, was the first signal.
Flexential's first official notification arrived at 12:28 UTC, roughly 44 minutes later.

## Resolution

1. Cloudflare failed over the affected control plane to disaster-recovery sites in Europe at 13:40
   UTC.
2. Applied emergency rate limiting to absorb a thundering-herd of retried API calls once the DR
   site came online.
3. Waited for Flexential to physically replace faulty circuit breakers and confirm stable power
   (achieved 22:48 UTC).
4. Performed a full, sequential cold-boot rebuild of PDX-04 starting 3 November - configuration-
   management servers first (~3 hours), then thousands of individual servers (10 min-2 hrs each)
   respecting dependencies.
5. All services fully restored by 4 November, 04:25 UTC.

## Action Items

- Require every Generally Available product/feature to run on the high-availability cluster with
  zero software dependencies on any single core facility. Owner: Platform/Control Plane Team.
  Priority: P0.
- Implement chaos testing that fully removes each entire core data center (not just its HA portion)
  to surface hidden single-facility dependencies. Owner: SRE/Reliability Team. Priority: P0.
- Require a tested, reliable disaster-recovery plan for every GA product/feature before launch.
  Owner: Product Engineering Teams. Priority: P0.
- Build a logging/analytics disaster-recovery plan that guarantees no log loss even if all core
  facilities fail simultaneously. Owner: Data/Logging Team. Priority: P1.
- Audit all core data center providers against Cloudflare's reliability standards, including
  notification SLAs for power-state changes. Owner: Infrastructure/Vendor Management. Priority: P1.
