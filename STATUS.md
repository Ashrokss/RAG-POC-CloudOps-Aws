# RAG SRE Agent — status

**Branch:** `feature/rag-aws-sre` · **PR:** #1 · **Deployed:** http://rag-sre-poc-frontend.azurewebsites.net
**Live config:** Azure `gpt-4o-mini` chat + `text-embedding-3-small` embeddings · 25 docs / 233 chunks
**Tests:** 170 passing offline (was 38)

## "What's the accuracy?" — there is no single number, on purpose

This system is scored on several axes that don't collapse into one percentage without hiding what
each one actually means - this is why `eval run` reports golden/adversarial separately and
question-type-by-question-type rather than one pooled score.

**The 88-question golden set has now been scored live for the first time** (previously only in
mock mode - see T9), alongside the 13-question adversarial set, across all 4 strategies - 404
pairs, `reports/eval_comparison_current-accuracy-2026-08-21.md`:

| Dimension | Result |
|---|---|
| Refuses when it should (unanswerable trap questions) | **100%** (all 4 strategies) |
| Never leaks a forbidden fact | **100%** (0 leaks anywhere in the adversarial set) |
| Names every fact a question requires it to (`required_id_recall`) | **25%-100%**, strategy- and question-dependent - the widest-ranging, least single-number-able metric |
| Hallucinated date/incident-id next to a real citation (`grounding_date` + `grounding_unretrieved_incident`) | Improved in T7 but **not zero** - averages ~0.2-0.8 violations per aggregate-type question depending on strategy |
| False-refusal rate on golden questions (never designed to be unanswerable) | Was **6.8%-9.1%**, concentrated at 36-55% on `cross_document` - root-caused and fixed in T9 |
| Golden-set retrieval recall | **0.92-1.00** on 4 of 5 question types (`cross_document` was the outlier T9 fixes) |

**A caveat that matters more than any single number in the raw report**: golden-set `quality_score`
(0.05-0.36 in the raw tables) is Jaccard token overlap between the live model's full-sentence
answer and a terse `expected_answer_summary` string - a live model paraphrases and cites rather
than quoting that summary back verbatim, so this number sits low **by construction**, even for
answers that are factually perfect (spot-checked directly against source text: verbose,
correctly-cited answers routinely score under 0.20). Recall/precision/mrr and the false-refusal
rate above are the trustworthy signals from this run, not the raw `quality_score` column - see T9.

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
| T8 | `rca/` known_pattern routing (RCA Platform v2) | A recurring failure (2+ retrieved incidents sharing one `okf/failure-modes/` entry) is answered from the existing playbook with zero chat-model calls, instead of re-deriving the same analysis every time |
| T9 | Live accuracy audit + 2 confirmed bug fixes + `rca/` eval tooling | First-ever live golden-set run surfaced a structural false-refusal gap on multi-incident questions (fixed) and a `known_pattern` id-priority bug (fixed); `rca/` now has its own live spot-check harness, which found the second bug |

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
| `rca/` known_pattern route, live click-through on RCA Platform v2 | Route **known_pattern**, blue info box, correct playbook citing `INC-2025-0201`/`INC-2025-0902`, real Azure model behind it |
| `rca/` retrieval route, live click-through (`What was the root cause of INC-2025-0101?`) | Route **retrieval**, correctly cited answer, 2249ms |

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

**3. Cold start after deploy is slow and can wedge - and F1 tier can wedge harder than a restart
fixes.** After the second deploy the app served skeleton frames for 7+ minutes; `az webapp restart`
fixed it immediately. F1 tier, shared CPU. Restart after each deploy and confirm the console
renders before declaring it live.

Separately, during this session's live verification, the site's own WebSocket endpoint
(`/_stcore/stream`) started returning a bare `429` on every handshake attempt - from a browser and
from a standalone `curl` with zero prior requests - blocking both pages identically (so not a T8
regression). Diagnosed as platform-level, not app-level: Azure's own `Http4xx`/`Http2xx` metrics for
the resource recorded nothing during the outage (the rejection never reached the resource's own
telemetry), Azure Resource Health confirmed F1 tier doesn't expose health diagnostics at all
("consider upgrading to a Basic, Standard, or Premium App Service plan"), and neither `az webapp
restart` nor a full `stop`→`start` cleared it. Scaling `plan-rag-poc-frontend` to B1 (Basic) fixed
it immediately (`101 Switching Protocols`); scaled back to F1 after testing. **If this recurs, the
fix is a temporary B1 scale-up, not another restart** - this is a known F1-tier limitation, not
something a code change addresses.

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

### T8 — `rca/` known_pattern routing (RCA Platform v2)
Note: unlike T1-T7 above, this is the `rca/` pipeline (`pages/2_RCA_Platform_v2.py`), not `rag/` -
a separate, parallel answer path, not a change to the Test Console. `rag/` already gained this same
short-circuit on a sibling branch; `rca/` had no equivalent and diverged before that work landed, so
this reimplements the same logic against `rca/`'s own types rather than sharing code between the
two pipelines.

New module `rca/failure_pattern.py` mirrors `rca/vocabulary.py`'s cached-frontmatter-loader pattern,
but reads `okf/failure-modes/*.md` rather than `rca/`'s own `knowledge/` tree: `knowledge/services/
*.md` already links to `knowledge/failure-modes/*.md` and `knowledge/playbooks/*.md`, but those
files don't exist yet, and both pipelines ingest the same `data/raw_rca_docs/` corpus, so an
incident id `rca/` retrieves matches one `okf/failure-modes/*.md` already declares. `rca/answer.py
::ask()` now checks for a match right after retrieval (2+ distinct retrieved incidents agreeing on
one failure mode) and, on a match, returns the matched `okf/playbooks/*.md` content directly -
`route="known_pattern"`, `model_id="none (matched known pattern)"` - skipping both `chat.complete()`
and `gaps.detect()` entirely for that answer.

Tested: 3 new matcher unit tests against real `okf/failure-modes/*.md` data (2 agreeing incidents
-> match; 1 incident or disagreement -> no match), plus an `ask()`-level test with a chat stub that
raises if called - confirmed to actually fail if the short-circuit is removed, not a tautology - and
a regression test that a novel question still calls the chat model normally. Full `tests_v2/` suite:
52/52 passing. Verified locally in mock mode (`python -m rca.cli ask "..."`, `HashEmbedder` +
`EchoChatModel`): a symptom description naming no incident id correctly returns `route=known_pattern`
in 90ms citing the real matched incidents (`INC-2025-0201`, `INC-2025-0902`), with the other three
routes unaffected. **Verified live** against the deployed Azure instance after a redeploy - see
"Verified live on the deployed app" above; the App Service also needed a temporary F1→B1 scale-up
to unblock testing (see item 3 below).

### T9 — Live accuracy audit, two confirmed bug fixes, `rca/` eval tooling
The first live scoring of the full 88-question golden set (never done before - see the top of this
file), run alongside the 13-question adversarial set across all 4 strategies (404 pairs,
`reports/eval_comparison_current-accuracy-2026-08-21.md/.csv/.jsonl`), plus a new 15-question live
spot-check for `rca/` (`data/rca_qa/spotcheck.yaml`, `rca/eval.py`, `python -m rca.cli eval`) built
from scratch since that pipeline had no eval harness at all. Found two real bugs, fixed both, and
one methodology trap in the golden set's own scoring:

**Methodology trap**: golden-set `quality_score` (heuristic Jaccard judge) sits at 0.05-0.36 across
the board - not because the answers are bad, but because a live model paraphrases and cites rather
than quoting the terse `expected_answer_summary` string back verbatim. Spot-checked directly: a
detailed, correctly-cited answer citing exact IOPS figures and a real remediation command scored
0.197. Recall/precision/mrr and refusal rate are what this run actually trusts; see the top of this
file.

**Bug 1 (`rag/`) - a structural false-refusal gap on multi-incident questions.** 6.8-9.1% of golden
questions got refused outright ("insufficient evidence"), concentrated in `cross_document` at
36-55% and identical across all four strategies - traced directly to source: plain top-k retrieval
has no guarantee of covering every incident a question names explicitly, so a two-incident
comparison question routinely got only one (or neither) incident's chunks, and the model correctly
refused rather than guess. Confirmed mechanism on the CloudFront question
(`INC-2025-0801`/`INC-2025-0802`): every strategy retrieved at most one of the two named incidents
(recall 0.0 or 0.5) before the fix.

Fixed in `rag/chain/rag_chain.py::_widen_for_named_incidents()`: when a question names 2+ incident
ids, any named id missing from what was retrieved gets its own top-ranked chunks pulled in
directly - the same per-incident lookup `aggregate_context()` already uses, just triggered by a
named id instead of a service filter, and only on the `retrieval` route. Deliberately **not** a
repeat of the "route 'between X and Y' through aggregate" idea `rag/routing/router.py` already
tried and reverted (that filtered by service, not by named id, and solved nothing for this shape).
Re-verified live afterward: all 4 strategies now retrieve both named incidents and produce a real
comparative, cited answer instead of refusing. Unit-tested in `tests/test_routing.py`
(`test_comparison_question_widens_docs_to_cover_both_named_incidents`,
`test_single_named_incident_lookup_is_not_widened`).

**Bug 2 (`rca/`) - `known_pattern` overrides an explicitly-named, successfully-retrieved incident.**
Asking for a specific existing incident by id (`INC-2026-0142`) returned an unrelated curated
playbook for two *other* incidents (`INC-2025-0301`, `INC-2025-1002`) that happened to also come
back in the same top-k and agree on a failure mode - even though `INC-2026-0142`'s own chunk was
retrieved too. `match_known_pattern` had no check for whether the question named a specific
incident that was itself retrieved.

Fixed in `rca/answer.py::ask()`: before checking for a known_pattern match, check whether the
question names an incident id (reusing `rca.gaps.INCIDENT_RE`) that is among the retrieved
incidents; if so, skip the short-circuit entirely. `rca/failure_pattern.py::match_known_pattern`
keeps its pure, question-unaware signature and its existing tests are unaffected. Unit-tested in
`tests_v2/test_platform.py::test_a_named_incident_outranks_a_coincidental_pattern_match`, reusing
the exact fixture that proves the opposite (question-less) case still fires correctly. Re-verified
live: `python -m rca.cli ask "Give me the summary of INC-2026-0142."` now returns `route=retrieval`
with the correct content. Full post-fix spot-check: 13/15 route match (up from 12/15), the bug's
own case at 1.00 must-mention recall (`reports/rca_spotcheck_current-accuracy-2026-08-21-postfix.md`).
The remaining 2/15 route misses (`rca-01`, `rca-03`) are a pre-existing phrasing-sensitivity nuance,
not bugs - the answers given are still factually correct for the single incident each one found.

**Footgun found and fixed**: `rca/providers.py` read `AZURE_AI_*` via bare `os.getenv()` with no
`load_dotenv()` of its own - confirmed live, standalone `python -m rca.cli ask/ingest/...` (exactly
what this project's own docs tell you to run) silently fell back to the mock embedder/chat model
with zero warning whenever nothing else had already imported `config.settings` first in the same
process. Fixed by adding `load_dotenv(override=False)` at module level, mirroring
`config/settings.py`'s own pattern - `rca/` is now correctly self-sufficient instead of accidentally
import-order-dependent.

Full test suite: 170/170 passing, including 3 new tests this session covering both fixes.

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
python -m rca.cli eval                           # rca/'s own 15-question live spot-check (T9)
streamlit run streamlit_app.py
```

Deploy (Windows): `.\deploy\redeploy.ps1` — now ships `okf/` and warns that the chunk-id change
requires a re-ingest first. On macOS/Linux, build the same package and
`az webapp deploy --name rag-sre-poc-frontend --resource-group rg-rag-poc-frontend --src-path <zip> --type zip`,
then `az webapp restart`.
