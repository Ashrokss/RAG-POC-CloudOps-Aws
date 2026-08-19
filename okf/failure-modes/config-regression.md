---
type: failure-mode
id: config-regression
name: Silent config or dependency regression
services: ["cloudfront", "ecr", "eventbridge", "iam", "s3"]
incident_ids: ["INC-2025-0301", "INC-2025-1002", "INC-2025-0901"]
---

## What it is

A change to policy, IaC tooling, or a dependency version silently drops or alters something a downstream consumer relied on - a permission statement, a variable a module used to read, a memory footprint - and nothing in the review or apply step surfaces the drop, because the diff is large, the failure mode is a silent fallback rather than an error, or nothing validated the new value against what the consumer actually needs.

## Seen in

- [INC-2025-0301](../../data/raw_rca_docs/synthetic/inc-2025-0301-s3-bucket-policy-regression.md) - a Terraform merge regenerating an S3 bucket policy referenced a stale data source instead of the checked-in JSON, silently dropping the `AllowCloudFrontOAI` statement; the plan's full-JSON diff didn't make the missing statement visually obvious to the reviewer, and every CloudFront-forwarded request got `403 Forbidden` for 26 minutes.
- [INC-2025-1002](../../data/raw_rca_docs/synthetic/inc-2025-1002-iam-trust-policy-regression.md) - a shared IAM Terraform module's input variable was renamed without deprecating the old name, so Terraform silently ignored the (now-unrecognized) old input and applied the module's test-fixture default trust policy to 38 roles - one of which broke a Lambda's ability to assume its own execution role for 84 minutes, while also adding an unintended wildcard-account principal.
- [INC-2025-0901](../../data/raw_rca_docs/synthetic/inc-2025-0901-ecs-oomkilled.md) - a dependency-upgrade deploy (`pandas`/`numpy`) changed steady-state memory footprint by roughly 1.7x with no test asserting on memory usage; the container's hard memory limit, sized for the old footprint, was never revisited (see [oom](oom.md)).
