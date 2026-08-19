# OKF Transition Plan

Reference: [GoogleCloudPlatform/knowledge-catalog/okf](https://github.com/GoogleCloudPlatform/knowledge-catalog/tree/main/okf) (spec v0.2).

## What OKF is

A vendor-neutral way to represent knowledge as plain markdown files with YAML frontmatter, designed to be read directly by humans and agents without a query language or proprietary store.

- **Required frontmatter**: `type` only. Everything else is optional, and consumers **must** tolerate unknown types/fields rather than reject them — the format is built to be extended without breaking existing readers.
- **Recommended frontmatter**: `title`, `description`, `resource` (a URI for the underlying asset), `tags`.
- **Provenance**: `generated: {by, at}` records who/what produced the content; `verified: [{by, at}]` records confirmation events against sources, giving a trust tier (unverified → machine-confirmed → human-reviewed). Actor ids follow a convention: `agent/version`, `human:id`, `process:id`.
- **Lifecycle**: `status` (`draft` / `stable` / `deprecated`) and `stale_after` (a date after which content is considered stale).
- **Bundle structure**: a directory of `.md` files, optionally with a root `index.md` (directory listing) and `log.md` (changelog). Concepts cross-link each other with plain markdown links.
- **Reference agent**: a two-pass generator (a "BQ pass" from structured metadata, a "web pass" via LLM + seed URLs) that drafts these documents; a human/reviewer is expected to curate the output, not treat it as final.

## What's already built here

This repo already has an OKF-inspired concept layer — **not a from-scratch idea, it's already in `feature/rag-aws-sre`** (see `docs/architecture.md`'s "The concept layer (`okf/`)" section):

- **`okf/services/*.md`** (21 files, one per AWS service) — each has frontmatter `type: service`, `id`, `name`, `aliases`, `depends_on`, `owned_by`, plus a body with "What it is" and "Known failure modes" (markdown links to `../failure-modes/*.md` — see gap below). Explicitly labelled as generated skeletons: *"the owning SRE must correct `owned_by`, `depends_on`, and the failure-mode list in PR review — curation is the point of this layer."*
- **`rag/ingestion/loader.py::service_alias_map()`/`canonical_service()`** — parses every `okf/services/*.md` file's `id`/`name`/`aliases` into a lowercase alias → canonical-id map, and normalizes the `services:` frontmatter field of every RCA doc against it at ingest. Before this, `"lambda"` vs `"Lambda"`, `"ec2"`/`"EC2"`, `"ELB"`/`"ALB"`/`"alb"` were distinct strings, so metadata filters silently missed half the matching corpus. An unrecognized service name is a warning naming the `okf/` file to add it to, never a hard failure — the curated layer is expected to lag the corpus on purpose.
- **`rag/routing/`** — `router.py` classifies each question as `retrieval` or `aggregate` (regex over a small closed vocabulary: "how many", "list every", "longest", "total", etc.) and resolves service names mentioned in a question to canonical ids via the same alias map. `incident_table.py` builds a structured one-row-per-incident index (date, severity, services, status, `detection_gap_minutes`, `duration_minutes`, `cost_usd`) so aggregate/ranking questions — which top-k retrieval structurally cannot answer, since the model only ever sees k chunks — get the full index handed to the model instead, filtered by any named service.

This is the load-bearing reason the concept layer exists: **service-name normalization was a prerequisite for the aggregate route**, not a parallel effort.

## Gap vs. the full OKF spec

| OKF v0.2 concept | Current `okf/services/*.md` | Assessment |
|---|---|---|
| `type` | present (`type: service`) | met |
| `title`/`tags` | `name` instead of `title`; no `tags` | close enough — rename is cosmetic, not worth churning |
| `resource` (asset URI) | absent (services are abstract concepts, not a single addressable resource) | not applicable |
| `generated`/`verified` (provenance) | absent | **deliberate gap** — every file is already 100%-human-PR-reviewed by design ("curation is the point of this layer"); provenance tracking earns its keep once generation is automated (e.g. an LLM drafts `okf/failure-modes/*.md` from incident text), not before |
| `stale_after` | absent | **worth revisiting once services/failure-modes reference specific AWS behavior** (API limits, default quotas) that changes over time — not urgent while the layer is 21 small, recently-authored files |
| bundle `index.md`/`log.md` | absent | **worth adding once `okf/` has more than one subdirectory** (see Phase 4) — right now `okf/services/` is the only one, so a listing adds little |
| cross-linking via markdown links | present (`../failure-modes/*.md` links from every service file) | met in spirit, but the **targets don't exist yet** — see Phase 1 |
| tolerant consumer (unknown fields never rejected) | **not met** — `rag/ingestion/loader.py::load_rca_documents` raises on invalid frontmatter (by design, for RCA docs: *"a bad RCA doc silently dropped... fails the eval harness in a way that looks like a retrieval bug, not an ingestion one"*) | intentional divergence for RCA docs specifically; the `okf/services/*.md` reader (`service_alias_map`) is already tolerant (an unknown service just warns) |

Net: the existing layer already made the right call adopting `type`/curation-by-PR and skipping provenance/staleness machinery this project doesn't need yet. The one real gap is the dangling `failure-modes` links.

## Next phases

Ordered by what's already half-built and referenced vs. speculative.

1. **`okf/failure-modes/*.md`** — every service file already links to these (e.g. `okf/services/ec2.md` → `../failure-modes/health-check-flapping.md`, `connection-draining.md`, `quota-exhaustion.md`; `s3.md` → `config-regression.md`, `replication-lag.md`, `regional-outage.md`). Writing these closes dangling links and gives `rag/routing/` a second concept type to route against — e.g. "what causes health-check flapping" could route to the failure-mode doc directly instead of chunk retrieval. Frontmatter: `type: failure-mode`, `id`, cross-links to `../services/*.md` and the incident ids that exhibited it (already named in the service files' body text).
2. **`okf/playbooks/*.md`** — remediation runbooks, one per failure mode, following the same PR-curated-skeleton pattern as `okf/services/`. Not RCA-specific (a playbook applies across incidents), so it's a genuinely new `type` rather than a variant of the existing RCA template. Links: playbook → failure-mode → service.
3. **Wire up `depends_on`** — already captured in every `okf/services/*.md` frontmatter but nothing reads it today. Once failure-modes exist, `rag/routing/router.py` could answer blast-radius-shaped questions ("what else breaks if RDS is down") by walking `depends_on` edges — a genuinely new question type, not answerable by retrieval or the current aggregate route.
4. **Bundle `index.md`/`log.md`** — once `okf/` holds `services/`, `failure-modes/`, and `playbooks/`, add a root `okf/index.md` (directory listing, OKF convention) so the concept layer is browsable on its own, and consider a `log.md` if curation activity (new/edited concept files) becomes something worth tracking separately from git history.
5. **Provenance/staleness (`generated`/`verified`/`stale_after`)** — revisit only if/when concept-file authoring stops being 100% human-reviewed-before-merge (e.g. an LLM drafts failure-mode or playbook skeletons the way the service skeletons were "generated from the corpus inventory"). Adding this now would track a trust distinction that doesn't exist yet.

## Verification

No new infrastructure needed — reuse what's already wired up:
- `python -m cli.ingest run --reset` — confirms new `okf/` concept files parse and `service_alias_map()` picks them up (unknown-service warnings in the log point at exactly what's missing).
- `pytest` (87/87 passing today) — extend `tests/test_routing.py` for any new route (failure-mode lookup, blast-radius) the same way aggregate routing is tested today.
- `python -m cli.eval run` — add golden/adversarial questions (`data/golden_qa/golden_qa.yaml`, `adversarial_qa.yaml`) once a new route exists, so the comparison report shows it's actually being exercised rather than dead code.
