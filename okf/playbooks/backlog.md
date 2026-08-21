---
type: playbook
id: backlog
name: Responding to a queue backing up behind an impaired consumer
failure_mode: backlog
services: ["sqs"]
owned_by: "TBD - set in review"
---

## When you see this

Queue depth climbing steadily with no unusual producer-side volume, and/or messages beginning to land in a dead-letter queue.

## Mitigate

1. Diagnose *why* the consumer is impaired - throttled below the volume it needs (see [throttling](throttling.md)) or crash-looping (see [oom](oom.md)) - rather than treating the backlog itself as the problem.
2. Fix the consumer; the queue drains on its own once it can keep pace again.
3. Manually redrive/reprocess any messages that already landed in the dead-letter queue, coordinating with the owning team if reprocessing needs sign-off.

## Prevent

- Alert on any message arriving in a dead-letter queue, rather than discovering it only during incident review.
- Add a pre-launch capacity checklist for consumers sitting in the critical path of any planned demand spike.
- Fix the underlying consumer impairment permanently (see the linked failure mode) rather than just raising queue-depth alarm thresholds to tolerate it.

## Related

- Failure mode: [Queue growing behind an impaired consumer](../failure-modes/backlog.md)
- Incidents: INC-2025-0202, INC-2025-0901
