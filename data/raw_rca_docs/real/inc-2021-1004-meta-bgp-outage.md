---
doc_id: "06fa99fa-ce29-4289-a8b0-3768ea4677bc"
incident_id: "INC-2021-1004-META-BGP"
title: "Meta Global BGP Route Withdrawal Causing Total DNS Unreachability for Facebook, Instagram, and WhatsApp"
date: "2021-10-04T15:39:00Z"
severity: critical
services: ["bgp", "dns", "backbone-network"]
region: "global"
account_id: "n/a"
status: "resolved"
tags: ["bgp", "dns", "network-outage", "blast-radius", "audit-tool-failure", "public-postmortem"]
source: real
---

## Summary

On October 4, 2021, Facebook, Instagram, WhatsApp, Messenger, and Oculus disappeared from the
internet simultaneously for approximately six hours. A routine backbone maintenance command
intended only to assess available capacity unintentionally disconnected all connections in
Facebook's global backbone network, isolating its data centers from each other and from the
internet. An internal audit tool specifically built to catch and block exactly this kind of overly
broad command failed to do so because of a bug in the tool itself. With the backbone down,
Facebook's DNS servers - designed to automatically withdraw their own BGP route advertisements if
they cannot reach Facebook's data centers as a safety mechanism - withdrew every route, making
facebook.com, instagram.com, and whatsapp.com globally unresolvable within minutes. Recovery was
severely delayed because Facebook's own internal tools, communications systems, and data center
badge readers all depended on the same failed network, forcing engineers to physically travel to
data centers to reset equipment locally.

## Timeline

- ~15:39 UTC - Facebook issues a large, sudden burst of BGP route withdrawals, externally observed
  in real time by Cloudflare and other internet monitoring services, covering hundreds of prefixes
  including all of Facebook's authoritative DNS nameservers.
- ~15:40 UTC - A backbone maintenance command intended only to assess available backbone capacity
  unintentionally disconnects all backbone connections between Facebook's data centers and the
  internet.
- ~15:40 UTC - Facebook's DNS servers, unable to reach the disconnected data centers, trigger their
  designed safety behavior and withdraw their own BGP advertisements.
- ~15:50 UTC - Facebook's domain names finish expiring out of DNS resolver caches worldwide;
  facebook.com, instagram.com, and whatsapp.com become globally unresolvable.
- ~15:45-16:00 UTC - Engineers discover that internal tools, Workplace (internal communications),
  and diagnostic systems are also unreachable, since they depend on the same internal DNS/network
  infrastructure.
- ~16:00 UTC onward - Engineers find they cannot remotely access affected routers/data centers; some
  badge-reader/physical access systems are also disabled by the same network outage.
- Afternoon UTC - Engineering and security teams arrange physical, on-site access so technicians can
  reach hardware directly and begin reversing the configuration.
- ~21:00 UTC - Facebook resumes announcing BGP routes for its prefixes.
- ~21:05-22:45 UTC - DNS resolution for Facebook domains is restored globally; traffic and services
  recover progressively as caches repopulate.

## Root Cause

A capacity-assessment maintenance command executed an action with blast radius across the entire
global backbone rather than being scoped to a smaller portion of the network, and the internal
audit tool specifically designed to catch and block exactly this class of overly broad, high-impact
command contained a bug that let the command through instead of stopping it. This was compounded by
a design coupling: the DNS failsafe (withdraw routes if data centers are unreachable) was a locally
reasonable safety mechanism that became a global amplifier once the entire backbone - not just one
path - went down simultaneously, converting an internal network problem into a total, externally
visible global outage.

## Impact

- Facebook, Instagram, WhatsApp, Messenger, and Oculus were globally unreachable simultaneously for
  approximately six hours - a total, worldwide outage, not regional or partial.
- Meta's own internal tools, including Workplace (internal communications), were unavailable.
- Physical badge-reader access systems at some data center facilities were affected, complicating
  on-site recovery.
- Third-party sites and apps using "Log in with Facebook" or Facebook/WhatsApp APIs also
  experienced failures, extending the blast radius beyond Meta's own products.

## Detection

Detected externally within moments by third-party BGP monitoring services (Cloudflare,
ThousandEyes), which observed the large-scale route withdrawal at ~15:39 UTC. Internally, engineers
quickly identified the DNS/BGP mechanism but were severely hampered in fixing it because the tools
normally used to investigate and remediate - remote access, internal communications, diagnostics -
all depended on the same broken network.

## Resolution

1. Engineering and security teams arranged physical, on-site access to data centers, since remote
   access tooling depended on the same broken network.
2. Technicians reached hardware directly and began reversing the backbone configuration change
   on-site.
3. Facebook resumed announcing BGP routes at ~21:00 UTC.
4. DNS resolution was restored globally over the following ~1-2 hours as caches worldwide
   repopulated and backend systems stabilized.

## Action Items

- Audit and harden the command-validation tooling itself; add automated testing and periodic
  verification that safety controls actually block the failure modes they claim to prevent.
- Re-evaluate failsafe mechanisms that can globally amplify a partial internal failure into a total
  external outage; consider more gradual or scoped withdrawal behavior.
- Build out-of-band recovery tooling and communication channels that do not depend on the company's
  own production network or DNS infrastructure.
- Ensure physical data center access systems have an independent, offline-capable fallback that does
  not depend on the same network being restored.
- Require staged, rate-limited, or scoped rollout for backbone/global configuration changes so a
  single command cannot affect the entire global network simultaneously.
- Regularly rehearse total-network-loss scenarios, including loss of remote access and internal
  communications, as part of disaster-recovery drills.
