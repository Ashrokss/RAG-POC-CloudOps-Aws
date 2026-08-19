---
doc_id: "f296bb79-05c7-4140-85c2-da97b5942a4d"
incident_id: "INC-2026-0142"
title: "Terraform Drift-Remediation Destroyed and Recreated prod-subnet-payments, Detaching NSGs"
date: "2026-08-11T21:40:00Z"
severity: high
services: ["azure-vnet", "terraform", "resource-sync-service", "nsg"]
region: "n/a (azure)"
account_id: "n/a"
status: "resolved"
tags: ["terraform", "iac-drift", "azure", "nsg", "change-management"]
source: real
---

## Summary

A nightly Terraform drift-remediation job auto-applied a plan against the production Azure virtual
network (prod-vnet), destroying and recreating the `prod-subnet-payments` subnet instead of
performing an in-place update, because the subnet's live CIDR had been manually edited in the Azure
Portal two weeks earlier without updating Terraform state. The recreation detached 3 network
security groups (NSGs) from the subnet, breaking connectivity for `resource-sync-service` (a
multi-cloud inventory sync service) and causing a 19-minute SLA breach for 2 enterprise tenants
(~340 end users).

## Timeline

- 03:10 AM IST - Terraform drift-remediation job starts via GitLab CI cron.
- 03:11 AM IST - `terraform apply` destroys and recreates `prod-subnet-payments`.
- 03:12 AM IST - PagerDuty alert fires: `resource-sync-service` health check failing.
- 03:14 AM IST - On-call SRE acknowledges and begins investigation.
- 03:19 AM IST - Root cause found: NSGs detached from the recreated subnet.
- 03:24 AM IST - NSGs manually re-associated via Azure CLI.
- 03:29 AM IST - Health checks pass; connectivity restored.
- 03:31 AM IST - Incident resolved.

## Root Cause

The subnet's live CIDR no longer matched the CIDR recorded in Terraform state - a drift caused by an
engineer manually changing the CIDR in the Azure Portal two weeks earlier without updating
Terraform. Because Terraform detected this as a property that cannot be updated in place, it chose
to destroy and recreate the subnet rather than apply an in-place update, which detached the
subnet's associated NSGs in the process. The nightly drift-remediation job applied this destructive
plan unattended, with no policy gate blocking manual out-of-band changes and no drift-detection
alerting in place before the job ran.

## Impact

- Services affected: `resource-sync-service` (multi-cloud inventory sync).
- Customers affected: 2 enterprise tenants (~340 end users).
- Duration: 19 minutes (03:10-03:29 AM IST).
- Business impact: SLA breach on both tenants; no data loss; no revenue impact (the recreated
  subnet had no stateful resources attached).

## Detection

Detected via an automated PagerDuty alert (`resource-sync-service` health check failing)
approximately 2 minutes after the destructive apply, not via a manual report. Detection speed was
assessed as adequate; the incident's most significant automation gap was the missing pre-apply
drift/destroy safeguard, not detection.

## Resolution

1. On-call SRE confirmed via Azure CLI (`az network vnet subnet show ... --query
   networkSecurityGroup`) that the NSG association had returned null - confirming NSG detachment.
2. Re-attached the 3 detached NSGs via `az network vnet subnet update ... --network-security-group
   prod-nsg-payments`.
3. Forced pods to reconnect via `kubectl rollout restart deploy/resource-sync-service -n prod` and
   verified recovery with a health-check curl returning HTTP 200.
4. Validated with `terraform plan -target=azurerm_subnet.payments` to confirm no further drift.

## Action Items

- Require approval for any Terraform plan containing a 'destroy' action on production-tagged
  resources. Owner: Platform Team. Priority: P0.
- Add daily automated drift-detection alerting. Owner: On-Call SRE. Priority: P1.
- Block manual Azure Portal edits on Terraform-managed resources via Azure Policy. Owner: Platform
  Team. Priority: P1.
