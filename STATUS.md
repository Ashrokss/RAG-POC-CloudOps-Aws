# RAG SRE Agent — status

**Branch:** `feature/rag-aws-sre` · **PR:** #1 · **Deployed:** http://rag-sre-poc-frontend.azurewebsites.net
**Live config:** Azure `gpt-4o-mini` chat + `text-embedding-3-small` embeddings · 25 docs / 233 chunks
**Tests:** 112 passing offline (was 38)

## "What's the accuracy?" — there is no single number, on purpose

This system is scored on several axes that don't collapse into one percentage without hiding what
each one actually means - this is why `eval run` reports golden/adversarial separately and
question-type-by-question-type rather than one pooled score. The real, current, live-verified
numbers (`reports/eval_comparison_live-adversarial-t7-grounding-fix.md`, 13 adversarial questions ×
4 strategies):

| Dimension | Result |
|---|---|
| Refuses when it should (unanswerable trap questions) | **100%** (13/13, all 4 strategies) |
| Never leaks a forbidden fact | **100%** (0 leaks anywhere in the adversarial set) |
| Names every fact a question requires it to (`required_id_recall`) | **25%-100%**, strategy- and question-dependent - the widest-ranging, least single-number-able metric |
| Hallucinated date/incident-id next to a real citation (`grounding_date` + `grounding_unretrieved_incident`) | Improved this session (see item 1 below) but **not zero** - averages ~0.2-0.8 violations per aggregate-type question depending on strategy |

**The 88-question golden set (ordinary Q&A) has never been scored live** - only in mock mode, which
the README already flags as producing artificially low scores since `MockChatModel` quotes text
verbatim instead of paraphrasing. So there is currently no live "how often does it get a normal
question right" percentage at all; only the 13-question adversarial set and 2 ad hoc blast_radius
questions have been checked against the real model. A live golden-set run (`python -m cli.eval run
--sets golden`, ~350 chat calls across 4 strategies) would be the way to get one, at a
proportionally larger cost.

> **Every eval report produced before the k-cap fix is void.** `hybrid` was returning up to 2k
> documents while every other strategy returned k, so it answered from double the context *and*
> was penalised on precision at the same time. Regenerate anything older than
> `reports/eval_comparison_t1-t5-baseline`.

---

## What shipped

| # | Change | Effect |
|---|---|---|
| T1 | Cap every strategy at k | Strategy comparisons are finally like-for-like |
| T2 | Adversarial question set + grounding checker | Refusals, enumerations and wrong-date/double-count answers now fail the eval instead of scoring well |
| T3 | Deterministic chunk ids + corpus caching | Re-ingest no longer duplicates the corpus; 26× faster retrieval |
| T4 | `okf/` service vocabulary | Metadata filters match the whole corpus instead of ~half |
| T5 | Aggregate routing | "How many / list every / longest / total" questions are answerable at all |
| T6 | okf/ failure-modes + playbooks + blast_radius routing | Every service->failure-mode link resolves, each has a remediation runbook, and "what else breaks if X is down" is answerable from the depends_on graph |
| T7 | blast_radius routing-regex fix + a generate()-level grounding retry | The dependency-impact route now actually triggers on natural phrasings; hallucinated incident-id/date claims get one automatic self-correction pass instead of shipping uncaught |
| — | Embedding-provenance guard | A mismatched index fails with one clear message instead of a Chroma dimension error per strategy |

### T1 — cap every strategy at k
`EnsembleRetriever` fuses two k-wide rankings by RRF and truncates nothing, so `hybrid` returned
9–10 chunks at k=5 and 18 at k=10 while the other three returned exactly k. `retrieve_only` now
truncates after dedup. Guarded by 16 test cases (4 strategies × k∈{1,3,5,10}); reverting the fix
fails 4 of them.

### T2 — an eval that can fail
- `data/golden_qa/adversarial_qa.yaml` — the 13 bake-off questions, with `expects_refusal`,
  `must_mention_ids`, `forbidden_ids`.
- `eval/grounding.py` — every date and figure stated next to an incident id must appear in that
  incident's retrieved text. Catches both real failures: the wrong date on `INC-2025-1002`, and
  `$41,400` from double-counting `$20,700`.
- `eval run` runs both question sets in one invocation and reports them **separately** — pooling
  86 easy questions with 13 hard ones would hide exactly what the hard ones test.

### T3 — performance and a silent data bug
`chunk_id` was `uuid4()` per call, so the same chunk had one id in Chroma and a different one at
query time. A second `ingest run` without `--reset` therefore **duplicated the whole corpus**
(the upsert deleted ids that never existed). Now `sha1(doc_id|section|ordinal)`.
Corpus and retriever are cached: **20 hybrid queries went 461 ms → 18 ms**; the full 396-pair eval
runs in ~5 s.

### T4 — controlled service vocabulary
21 curated files in `okf/services/`. `services:` frontmatter was free text written by several
people — `lambda`/`Lambda` (5 docs each), `ec2`/`EC2`, `api-gateway`/`API Gateway`, `ELB`/`ALB`/`alb`
— so any metadata filter matched about half the corpus. Now **50 raw values → 38 canonical ids,
zero case or hyphenation variants**. Unknown names warn and pass through; they never fail an ingest.

### T5 — aggregate routing
Top-k retrieval structurally cannot answer "which incident had the longest detection gap" — the
model only ever sees k chunks. `rag/routing/` adds an incident table (one row per doc, including
`detection_gap_minutes`, `duration_minutes`, `cost_usd` backfilled into all 25 docs' frontmatter
from their own Impact/Detection sections) and a regex router. Aggregate questions get the filtered
index **plus** chunk text for every incident it lists, so answers stay citable. `RAGAnswer.route`
records the path; the console shows it.

### T6 — okf/ failure-modes, playbooks, and dependency-graph routing
`okf/services/*.md`'s `../failure-modes/*.md` links all pointed at files that didn't exist yet;
`okf/failure-modes/` (18 files, one per failure mode named across the 21 service files) closes
every one of them, grounded in the actual incident RCA text rather than the service skeletons'
one-line descriptions. `okf/playbooks/` (18 files) adds a remediation runbook per failure mode -
signals, immediate mitigation, prevention - synthesized from the Resolution/Action Items sections
of the incidents that exhibit it, cross-linked back to the failure mode and forward to related
ones (`backlog` -> `throttling`/`oom`, `timeout` -> `iops-throttling`). One factual correction
surfaced in the process: `okf/services/kms.md` and `s3.md` both described INC-2025-0302 as a KMS
*permission* problem; the RCA's actual root cause is KMS *request-rate throttling* (a quota, not a
policy denial) - fixed, and both now link to a new `throttling.md`.

`depends_on` (present in every service file's frontmatter, unused until now) now feeds a third
route, `blast_radius`: `rag/routing/dependency_graph.py` inverts the forward depends_on graph and
walks it breadth-first, so "what services depend on RDS" reports Glue (direct) and Step Functions
(transitive, two hops) rather than only direct dependents. The graph has a real cycle (`alb` and
`ecs` each depend on the other) - `downstream_of()` is visited-tracked specifically because of it.
Two new golden questions (`question_type: blast_radius`) exercise it; the 88-question golden set
count and the "all answerable from one retrievable chunk" description of it were updated to match,
since these two are answered from `okf/` instead.

### T7 — blast_radius routing fix, and a self-correcting generate()
Two fixes, found chasing what first looked like one bug. `_BLAST_RADIUS_RE` required the literal
adjacent phrase "affected if"; "what would be affected **downstream** if X had an outage" - a
natural way to ask this - has a word in between and silently fell through to plain `retrieval`
with no dependency graph in its context at all. Fixed by tolerating up to 3 words between the
trigger verb and "if"; re-checked against every golden/adversarial question afterward to confirm
nothing else newly misclassified.

Separately, `generate()`'s single "retry once" step is now `_find_corrections()` - one place that
gathers every issue (missing citation, a `blast_radius` answer omitting a listed service, a
hallucinated date/incident-id `check_grounding` catches) before one combined retry, instead of
several independent retry-and-re-check passes that could each perturb the answer. `check_grounding`
and `check_dependency_completeness` both moved from `eval/` into `rag/chain/` and `rag/routing/`
respectively, since `generate()` now calls them directly on the live answer path, not only eval
scoring after the fact - `rag/` must not depend on `eval/`. All of it is unit-tested with a scripted
stub chat model (`tests/test_rag_chain.py`), not only live spot-checks.

---

## Verified live on the deployed app

| Check | Result |
|---|---|
| `List every incident involving AWS Lambda…` | Route **aggregate**, 8 incidents enumerated chronologically, 8 citations resolved, **every date correct** — including `INC-2025-1002` on **2 Oct** (the bake-off dated it 30 May) |
| `Which incident had the longest detection gap…` | Route **aggregate**, correctly identifies **INC-2025-0302** and its fix. All four strategies failed this at the bake-off |
| `semantic` / `hybrid` / `hybrid_rerank` | Working after the index rebuild (see below) |
| Health probe | HTTP 200, startup probe 42 s |

---

## Needs attention

**1. Answers still get quantities wrong - partially improved, not solved.** The original bug: the
detection-gap answer named the right incident but said "~4 h 12 m" where the doc says **6 h 27 m**
(4 h 12 m is the data-staleness figure from the *same* document). That specific class - a real
figure, just the wrong one from a document that states several - is structurally invisible to
`check_grounding` (moved to `rag/chain/grounding.py`): both numbers genuinely appear somewhere in
that incident's text, so nothing looks unsupported. A lexical presence check cannot tell "wrong
figure, right document" from "right figure" without understanding what was asked; that needs an
NLI/claim-extraction model, not a regex, and is out of scope for this pass.

What *is* now fixed: `generate()` self-corrects when a citation names an incident id or date that
never appears in the retrieved text at all (pure hallucination, not "wrong nearby figure") - one
retry, gathered together with any other issue found (see T7). Also added: an explicit prompt
warning about this exact adjacent-figure confusion (detection gap vs. total duration vs.
data-staleness window, all in one document). Re-ran the live adversarial set before/after
(`eval_comparison_live-adversarial-t6.md` → `-t7-grounding-fix.md`), aggregate-type questions only:

| Strategy | date viol. (before → after) | unretrieved-id viol. (before → after) | quality_score (before → after) |
|---|---|---|---|
| hybrid | 0.83 → 0.83 | 0.33 → **0.00** | 0.495 → 0.542 |
| hybrid_rerank | 0.83 → 0.83 | 0.00 → 0.00 | 0.578 → 0.664 |
| keyword | 0.83 → 0.83 | 0.50 → **0.17** | 0.516 → 0.563 |
| semantic | 0.83 → **0.17** | 0.50 → 0.33 | 0.662 → 0.624 (dipped slightly - `required_id_recall` also moved on this run, and quality_score averages several components together) |

Honest read: hallucinated incident-id references dropped meaningfully on 3 of 4 strategies, and
`semantic`'s date violations dropped from 0.83 to 0.17 - real, live-verified improvement. Date
violations did **not** move on the other three strategies. Given the original bug report was
specifically the wrong-nearby-figure case, this fix does not claim to have resolved it - only the
narrower, outright-fabrication case it can actually see. `number` violations (aggregate totals)
were deliberately left out of the retry trigger, since a legitimate total is *supposed* to be a
figure absent from the source - that's the point of asking for one - so those counts moved on their
own (live model variance) and aren't a signal either way.

**2. The index and the app must agree on the embedding model.** The shipped index had been built
with mock embeddings (256-dim) while the live app embeds queries with `text-embedding-3-small`
(1536-dim), which broke 3 of 4 strategies with `Collection expecting embedding with dimension of
256, got 1536`. Fixed by rebuilding the index against the live deployment, and a guard now stamps
the embedding model into the collection and fails with one clear message on mismatch. **Anyone
redeploying must re-ingest with the same provider the app is configured for.**

**3. Cold start after deploy is slow and can wedge.** After the second deploy the app served
skeleton frames for 7+ minutes; `az webapp restart` fixed it immediately. F1 tier, shared CPU.
Restart after each deploy and confirm the console renders before declaring it live.

**4. ~~Refusal behaviour is unverified.~~ Verified live** (`reports/eval_comparison_live-adversarial-t6.md`,
reconfirmed unchanged in `-t7-grounding-fix.md`): `refusal_correct = 1.000` on both "unanswerable"
trap questions, across all four strategies. No forbidden-id leakage anywhere in the adversarial set
either. The `aggregate`-type adversarial questions remain the weak spot live - see item 1 above for
the current before/after numbers and what's actually fixed versus still open.

**5. `okf/` skeletons need their owners.** (The team's `okf/failure-modes/*.md` and
`okf/playbooks/*.md` have since landed on the branch - all 18 failure-mode slugs the service files
link to now resolve, each with a playbook. `depends_on` is also now consumed, by the new
`blast_radius` route, rather than sitting unused.) Every service file still says
`owned_by: "TBD - set in review"`. The aliases are correct (generated from the corpus); ownership,
and whether each `depends_on` edge is actually correct (`alb`/`ecs` currently depend on each
other, which is architecturally suspect and wasn't ground-truthed against any incident the way the
kms/s3 correction above was), need the owning SRE before merge. 17 service names still unclaimed —
`terraform`, `kafka`, `bgp`, `clickhouse`, `nsg`, `azure-vnet` and similar — each a genuine "does
this deserve a concept file?" call.

**6. `api/main.py` has no authentication**, and Chroma persists to container-local disk (no shared
state across instances, re-ingest on every redeploy). Both flagged, neither in scope for this pass.

**7. ~~`blast_radius` under-reports transitive dependents~~ Fixed - it was a routing bug, not the model
dropping facts.** The original diagnosis blamed the model: asked live "what would be affected
downstream if ACM had an outage," it named only 2 of 4 services the dependency graph says are
affected. That diagnosis was wrong, and wrong for an instructive reason - the "verification" that
the model had all four in front of it called `blast_radius_context()` directly, which builds the
block unconditionally and does not go through `classify()`. Checking `classify()` itself on the
exact question wording showed the real bug: `_BLAST_RADIUS_RE` required the literal adjacent phrase
"affected if", and "affected **downstream** if" - an entirely natural way to ask this - has a word
in between and doesn't match it. The question was routing to plain `retrieval` the whole time, with
no dependency graph in its context at all; the model was never given the two services it "dropped."
Confirmed directly (`classify(...)` returned `"retrieval"`), fixed (the regex now tolerates up to 3
words between the trigger verb and "if"), and re-checked against every golden/adversarial question
to confirm nothing else newly misclassified. Re-verified live afterward: the ACM question now
correctly lists all four (`alb, cloudfront, ecs, route-53`) with zero citations, as designed.

Two smaller improvements made while chasing the wrong theory were kept anyway, since they're correct
independent of it: the citation retry in `generate()` no longer fires for a `### DEPENDENCY IMPACT
###` answer (it's designed to have zero citations unless an excerpt backs one - retrying it with
"cite every claim or drop it" was always a latent bug waiting to matter), and a new
`check_dependency_completeness()` (`rag/routing/dependency_graph.py`) triggers one retry naming
exactly what's missing if a model ever does drop a listed service for a different reason. Both are
unit-tested with a scripted stub model, not just live spot-checks.

---

## Out of scope for this pass

The agentic loop (decompose → multi-retrieve → self-check → structured RCA with 5-Whys),
document-level ABAC, and moving Chroma off container-local disk. Sequence those now that the eval
harness can detect a regression.

---

## Running it

```bash
python -m cli.ingest run --reset                 # re-index (must match the app's embedding model)
python -m cli.eval run                           # both question sets, reported separately
python -m cli.eval run --sets adversarial --k 10 # retrieval-depth check
python -m cli.query ask "<question>" --strategy hybrid
streamlit run streamlit_app.py
```

Deploy (Windows): `.\deploy\redeploy.ps1` — now ships `okf/` and warns that the chunk-id change
requires a re-ingest first. On macOS/Linux, build the same package and
`az webapp deploy --name rag-sre-poc-frontend --resource-group rg-rag-poc-frontend --src-path <zip> --type zip`,
then `az webapp restart`.
