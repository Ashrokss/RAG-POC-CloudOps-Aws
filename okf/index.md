# okf/ concept layer

A curated knowledge bundle for the AWS SRE Agent, consumed by `rag/ingestion/loader.py`
(service-name normalization at ingest) and `rag/routing/` (the `aggregate` and
`blast_radius` routes). See `docs/architecture.md`'s "The concept layer" and "Three routes"
sections for how the code reads this bundle, and `plan.md` for how it maps onto the OKF
specification and where it deliberately diverges (no `generated`/`verified`/`stale_after` -
every file here is human-PR-reviewed by design, not machine-generated at run time).

## Subdirectories

* [services](services/index.md) - one file per AWS service named in the incident corpus: canonical id, aliases actually seen in the frontmatter, `depends_on`, `owned_by`, and the failure modes it's known to exhibit.
* [failure-modes](failure-modes/index.md) - one file per failure mode named across the service files, grounded in the incidents that exhibit it, cross-linked back to the services and forward to a playbook.
* [playbooks](playbooks/index.md) - one remediation runbook per failure mode: the signals that identify it, immediate mitigation, and structural prevention.
