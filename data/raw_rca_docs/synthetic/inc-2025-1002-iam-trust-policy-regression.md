---
doc_id: "f0351ec8-1a0b-4015-b0c1-0a7842c9b185"
incident_id: "INC-2025-1002"
title: "Regressed IAM Trust Policy Blocks Scheduled Billing Reconciliation Lambda"
date: "2025-10-02T07:00:00Z"
severity: high
services: ["lambda", "iam", "eventbridge"]
region: "us-west-2"
account_id: "294817360055"
status: "resolved"
tags: ["iam", "permissions", "lambda", "regression", "terraform"]
source: synthetic
---

## Summary

A shared Terraform module used to manage IAM role trust policies was bumped from v2.3.0 to v3.0.0 as
part of a security-hardening initiative. A renamed input variable was silently ignored by the new
module version, causing it to fall back to a default trust policy template on 38 IAM roles, including
`nightly-billing-reconciler-role`. That default template added an `sts:ExternalId` condition to the
`lambda.amazonaws.com` service-principal statement - a condition the Lambda service never satisfies -
while also adding an unrelated wildcard `AWS: "arn:aws:iam::*:root"` principal intended only for a
test fixture, making the policy simultaneously broken for its intended purpose and overly permissive.
The next scheduled invocation of `nightly-billing-reconciler` failed outright because Lambda could no
longer assume its own execution role.

## Timeline

- **2025-10-01 16:40 UTC** - PR #4127 merges a bump of shared Terraform module `modules/iam-role` from
  v2.3.0 to v3.0.0 across 38 IAM roles as part of hardening initiative SEC-881.
- **2025-10-01 17:05 UTC** - The nightly CI/CD pipeline runs `terraform apply`; it completes with no
  errors because the module's renamed variable (`trusted_service_principals` -> `principal_services`)
  is accepted as an unused, silently-ignored input rather than causing a plan failure.
- **2025-10-02 07:00:00 UTC** - EventBridge rule
  `arn:aws:events:us-west-2:294817360055:rule/nightly-billing-reconciler-schedule`
  (`cron(0 7 * * ? *)`) triggers the scheduled invocation of
  `arn:aws:lambda:us-west-2:294817360055:function:nightly-billing-reconciler`.
- **07:00:03 UTC** - The invocation fails immediately with
  `InvalidParameterValueException: The role defined for the function cannot be assumed by Lambda.`
  No function-level CloudWatch Logs stream is created because execution never starts.
- **07:15 UTC** - CloudWatch alarm `nightly-billing-reconciler-Errors`, based on the EventBridge rule's
  `FailedInvocations` metric, fires and pages billing on-call.
- **07:32 UTC** - On-call reviews CloudTrail and finds `AssumeRole` calls for
  `nightly-billing-reconciler-role` failing with `errorCode: "AccessDenied"`, with additional event
  data referencing the `sts:ExternalId` condition.
- **07:50 UTC** - `aws iam get-role --role-name nightly-billing-reconciler-role` shows the
  `AssumeRolePolicyDocument` now includes `"ec2.amazonaws.com"` and `"arn:aws:iam::*:root"` as
  principals plus the `sts:ExternalId` condition - none of which were present in the last known-good
  version in git history.
- **08:05 UTC** - Root cause traced to the Terraform module bump in PR #4127 and the silent variable
  rename.
- **08:12 UTC** - Mitigation: `aws iam update-assume-role-policy` manually restores the last-known-good
  trust policy JSON; the function is invoked manually via `aws lambda invoke` to run the delayed
  reconciliation.
- **08:24 UTC** - Manual reconciliation run completes successfully; billing export files for the 07:00
  UTC window are produced.
- **08:40 UTC** - Terraform state is reconciled by pinning the affected roles back to
  `modules/iam-role` v2.3.0, preventing the next `terraform apply` from reintroducing the regression;
  incident closed.

## Root Cause

The Lambda service must assume a function's execution role using the `lambda.amazonaws.com` service
principal, and service principals never supply an `sts:ExternalId` when assuming a role. Terraform
module `modules/iam-role` v3.0.0 renamed its input variable from `trusted_service_principals` to
`principal_services` but did not deprecate or validate the old name, so Terraform silently dropped the
now-unrecognized input and applied the module's internal default trust policy template instead. That
default template - written for the module's test fixtures, not for production use - attached an
`sts:ExternalId` condition to every principal statement, including the `lambda.amazonaws.com`
statement, and added an `ec2.amazonaws.com` service principal and a wildcard
`"AWS": "arn:aws:iam::*:root"` principal that were never intended to ship. The `ExternalId`
condition on the service-principal statement caused every subsequent Lambda `AssumeRole` attempt to
be denied, while the wildcard root principal simultaneously made the role's trust policy overly
permissive to any AWS account. The trigger was the module version bump; the root cause was the
absence of input validation in the module combined with no automated drift detection on trust
policy content.

## Impact

`nightly-billing-reconciler` failed to run at its scheduled 07:00 UTC time, delaying billing export
generation for approximately 120 downstream customer accounts by 1 hour 24 minutes. Four enterprise
customers' automated invoice-ingestion pipelines retried against an empty S3 prefix and raised their
own internal alerts. Separately, all 38 IAM roles affected by the module bump carried the
overly-permissive wildcard-account trust statement for approximately 15.5 hours (17:05 UTC on
2025-10-01 to 08:40 UTC on 2025-10-02); a CloudTrail review of `AssumeRole` events during that window
found no evidence of exploitation from unexpected external account IDs.

## Detection

Detected automatically via the CloudWatch alarm `nightly-billing-reconciler-Errors`, driven by the
EventBridge rule's `FailedInvocations` metric, at 07:15 UTC - 15 minutes after the scheduled trigger
time. Detection relied on the rule-level metric because the invocation failed before any
function-level Lambda metrics were emitted.

## Resolution

1. Manually restored the last-known-good `AssumeRolePolicyDocument` on
   `nightly-billing-reconciler-role` via `aws iam update-assume-role-policy`.
2. Manually invoked `nightly-billing-reconciler` to produce the delayed billing exports.
3. Pinned all 38 affected roles' Terraform module reference back to `modules/iam-role` v2.3.0 to
   prevent the next scheduled `terraform apply` from reapplying the regression.

## Action Items

1. Add a `terraform plan` CI gate that fails the pipeline on any unrecognized or unused input variable
   passed to a shared module. Owner: platform-security, ticket SEC-902.
2. Add a nightly automated diff/drift check across all IAM role trust policies against a checked-in
   allowlist, alerting on any `Principal` containing a wildcard account or an unexpected service.
3. Add a CloudWatch alarm directly on the Lambda function's own error/invocation metrics in addition
   to the EventBridge rule's `FailedInvocations` metric, so assume-role failures are caught regardless
   of trigger source.
4. Require two-reviewer approval plus an `aws iam simulate-principal-policy` run in CI before merging
   any change that touches a shared IAM trust-policy module.
