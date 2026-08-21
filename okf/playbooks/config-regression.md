---
type: playbook
id: config-regression
name: Responding to a silent config or dependency regression
failure_mode: config-regression
services: ["cloudfront", "ecr", "eventbridge", "iam", "s3"]
owned_by: "TBD - set in review"
---

## When you see this

A permission, routing, or resource-usage change immediately following a merge/apply with no corresponding application-code change; the resource's live/applied state doesn't match what a quick read of the diff would suggest.

## Mitigate

1. Diff the resource's actual applied state (`terraform state show`, `aws iam get-role`, live config) against the last known-good version in git history - don't assume the new code did what its diff implied.
2. Roll back to the prior state via a targeted apply or manual restore, prioritizing time-to-recovery over a forward-fix under incident pressure.
3. Reopen the original change as a new PR requiring an explicit, statement-by-statement (not whole-document) diff before it merges again.

## Prevent

- Require statement-by-statement policy diffs in review for any change touching a bucket policy, trust policy, or other security-sensitive generated document - a large JSON diff hides a missing statement in plain sight.
- Add a CI/plan check that fails the build if a shared module silently accepts an unrecognized or renamed input variable instead of erroring.
- Add a memory/resource-footprint regression gate to dependency-upgrade pipelines, since a "config" regression can just as easily be a runtime footprint change nothing asserted on.
- Audit other resources generated the same way for the same class of silent-drop failure.

## Related

- Failure mode: [Silent config or dependency regression](../failure-modes/config-regression.md)
- Incidents: INC-2025-0301, INC-2025-1002, INC-2025-0901
