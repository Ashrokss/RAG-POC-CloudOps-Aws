---
type: failure-mode
id: cert-expiry
name: Certificate renewal silently broken
services: ["acm", "alb", "cloudfront", "route-53"]
incident_ids: ["INC-2025-0801"]
---

## What it is

A certificate's automatic renewal silently stops working - most often because a DNS validation record it depends on was removed by an unrelated change - and the failure-notification channel isn't actively monitored, so nothing surfaces until the certificate actually expires and every HTTPS request in front of it starts failing TLS handshake.

## Seen in

- [INC-2025-0801](../../data/raw_rca_docs/synthetic/inc-2025-0801-cloudfront-cert-expiry.md) - a Route 53 hosted-zone cleanup deleted the ACM DNS validation CNAME 63 days before expiry, silently disabling renewal; ACM's renewal-failure emails went to an unmonitored alias, and the certificate (shared by a CloudFront distribution and an ALB listener) expired outright, failing 100% of HTTPS traffic for 1h12m.
