---
doc_id: "5040b325-bf2f-4ffb-8f90-c1a89f69e831"
incident_id: "INC-2025-0801"
title: "CloudFront and ALB HTTPS Outage from Expired ACM Certificate"
date: "2025-08-09T00:00:00Z"
severity: critical
services: ["CloudFront", "ALB", "ACM", "Route 53"]
region: "us-east-1"
account_id: "174608392251"
status: "resolved"
tags: ["cloudfront", "acm", "tls", "certificate-expiry", "outage", "dns"]
source: synthetic
# Extracted by hand from this document's own Impact and Detection sections
# so aggregate questions (longest detection gap, total cost, duration
# ranking) can be answered by sorting a column instead of hoping top-k
# retrieval happens to surface every relevant doc. null = not stated above.
detection_gap_minutes: 3
duration_minutes: 72
cost_usd: 85000
---

## Summary

The ACM certificate backing CloudFront distribution `E1A2B3C4D5E6F7` (`www.acmecloudops.com`)
and the `prod-public-alb` listener expired at 2025-08-09T00:00:00Z. ACM could not auto-renew it
because the DNS validation CNAME it depends on had been deleted from Route 53 during an unrelated
hosted-zone cleanup 63 days earlier, and the resulting renewal-failure emails went to an
unmonitored alias. HTTPS to `www.acmecloudops.com` failed for 1 hour 12 minutes, affecting an
estimated 14,600 customers and costing an estimated $85,000 in lost checkout revenue.

## Timeline

- 2025-06-07T00:00:00Z - During cleanup ticket JIRA-8890, an engineer removes CNAME
  `_a79865eb4cd1a6ab990a8588e3a5c.acmecloudops.com` - the ACM DNS validation record for
  `www.acmecloudops.com` - believing it unused. This silently disables auto-renewal.
- 2025-06-11T00:00:00Z through 2025-08-08T - ACM sends renewal-failure emails to
  `aws-notifications@acmecloudops.com`, an alias with no active subscriber; none are actioned.
- 2025-08-09T00:00:00Z - Certificate
  `arn:aws:acm:us-east-1:174608392251:certificate/9f8e7d6c-5b4a-3c2d-1e0f-abcdef123456` reaches
  its `NotAfter` timestamp and expires.
- 2025-08-09T00:03:12Z - Route 53 health check `www-acmecloudops-https-check` reports `Failure`
  (`SSL: certificate verify failed`), triggering a CloudWatch alarm that pages on-call.
- 2025-08-09T00:06:40Z - On-call reproduces the failure: `curl -v https://www.acmecloudops.com`
  returns `curl: (60) SSL certificate problem: certificate has expired`; browsers show
  `NET::ERR_CERT_DATE_INVALID`. `prod-public-alb` fails identically (shared wildcard cert).
- 2025-08-09T00:14:00Z - ACM console shows renewal status `FAILED` ("domain validation records
  not found"); the validation CNAME is confirmed missing from hosted zone `Z0912ABCXYZ`.
- 2025-08-09T00:38:00Z - Rather than wait for re-validation, on-call requests a new ACM
  certificate with DNS validation and creates the new validation CNAME in `Z0912ABCXYZ`
  immediately.
- 2025-08-09T00:52:00Z - New certificate reaches `ISSUED`; CloudFront distribution
  `E1A2B3C4D5E6F7` is updated via `UpdateDistribution` to the new certificate ARN.
- 2025-08-09T01:12:00Z - `curl -v` returns HTTP 200 and the health check returns to `Success`;
  the same certificate is attached to the ALB listener and the incident is resolved.

## Root Cause

The certificate relied on DNS validation for automatic renewal. An unrelated Route 53 cleanup
deleted its validation CNAME because nothing in the cleanup process cross-referenced active ACM
certificates, silently breaking re-validation roughly 60 days before expiry - when ACM begins
attempting renewal. ACM's renewal-failure emails went to an alias with no active subscriber, so
the failure went unnoticed for the full window. No CloudWatch alarm or Config rule tracked the
certificate's `DaysToExpiry` independently, so the unmonitored email was the only remaining
safeguard, and it did not hold.

## Impact

- 100% of HTTPS traffic to `www.acmecloudops.com` failed for 1 hour 12 minutes
  (00:03:12Z-01:12:00Z); `prod-public-alb` failed identically for the same duration.
- An estimated 14,600 customers could not load the site or complete login/checkout.
- 340 support tickets filed referencing a browser security warning or "site not loading."
- Estimated $85,000 in lost checkout revenue based on the average revenue run-rate for the window.
- A public status page incident was posted at 00:19:00Z and resolved at 01:15:00Z.

## Detection

Route 53 health check `www-acmecloudops-https-check` transitioned to `Failure` 3 minutes 12
seconds after expiry, triggering a CloudWatch alarm. CloudFront access logs do not capture TLS
handshake failures (they occur before the HTTP layer), so the health check and early support
tickets were the only signals until on-call reproduced the failure directly.

## Resolution

1. Reproduced the failure and confirmed via the ACM console that renewal had failed due to a
   missing DNS validation record.
2. Requested a new ACM certificate with DNS validation rather than waiting on the original's
   re-validation cycle, prioritizing time-to-recovery.
3. Created the new validation CNAME in `Z0912ABCXYZ` and monitored ACM until `ISSUED` (14 minutes
   later).
4. Updated CloudFront's viewer certificate via `UpdateDistribution` and attached the same
   certificate to the ALB listener.
5. Verified recovery via `curl -v` (HTTP 200) and the health check returning to `Success` before
   declaring the incident resolved.

## Action Items

1. Deploy AWS Config rule `acm-certificate-expiration-check` (threshold 45 days) account-wide,
   routed to PagerDuty rather than email only. Owner: Security/SRE team. Ticket: JIRA-9001.
2. Build a weekly automated check that verifies every ACM certificate's DNS validation record is
   present and resolves correctly, alerting on drift. Owner: SRE team. Ticket: JIRA-9002.
3. Add a CloudWatch dashboard and alarm on ACM `DaysToExpiry` for all customer-facing
   certificates. Owner: SRE team. Ticket: JIRA-9003.
4. Require shared-hosted-zone CNAME deletions to go through a review checklist cross-referencing
   active ACM validation records. Owner: Platform/Security team. Ticket: JIRA-9004.
