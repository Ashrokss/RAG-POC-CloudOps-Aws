---
type: playbook
id: cert-expiry
name: Responding to an expired certificate
failure_mode: cert-expiry
services: ["acm", "alb", "cloudfront", "route-53"]
owned_by: "TBD - set in review"
---

## When you see this

`NET::ERR_CERT_DATE_INVALID`, `SSL certificate verify failed`, or a DNS/HTTPS health check transitioning to failure with no application-side change.

## Mitigate

1. Confirm expiry and cause via the certificate console - a `FAILED` renewal status names the reason (most often a missing DNS validation record).
2. Request a new certificate with DNS validation immediately rather than waiting on re-validation of the original; prioritize time-to-recovery over reusing the existing certificate resource.
3. Attach the new certificate to every consumer (CDN distribution, load balancer listener) sharing the expired one.

## Prevent

- Deploy an automated certificate-expiration check (e.g. AWS Config `acm-certificate-expiration-check`) routed to PagerDuty, not email.
- Run a recurring automated check that every certificate's DNS validation record is still present and resolves correctly.
- Route any hosted-zone cleanup through a review step that cross-references active certificate validation records before deleting a CNAME.

## Related

- Failure mode: [Certificate renewal silently broken](../failure-modes/cert-expiry.md)
- Incidents: INC-2025-0801
