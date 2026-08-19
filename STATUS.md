# RAG SRE Agent — status

**Branch:** `feature/rag-aws-sre` · **PR:** #1 · **Deployed:** http://rag-sre-poc-frontend.azurewebsites.net
**Live config:** Azure `gpt-4o-mini` chat + `text-embedding-3-small` embeddings · 25 docs / 233 chunks
**Tests:** 92 passing offline (was 38)

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

**1. Answers still get quantities wrong.** The detection-gap answer named the right incident but
said "~4 h 12 m" where the doc says **6 h 27 m** (4 h 12 m is the data-staleness figure from the
same document). Right incident, wrong number — exactly the class `eval/grounding.py` exists to
count. Worth a prompt iteration.

**2. The index and the app must agree on the embedding model.** The shipped index had been built
with mock embeddings (256-dim) while the live app embeds queries with `text-embedding-3-small`
(1536-dim), which broke 3 of 4 strategies with `Collection expecting embedding with dimension of
256, got 1536`. Fixed by rebuilding the index against the live deployment, and a guard now stamps
the embedding model into the collection and fails with one clear message on mismatch. **Anyone
redeploying must re-ingest with the same provider the app is configured for.**

**3. Cold start after deploy is slow and can wedge.** After the second deploy the app served
skeleton frames for 7+ minutes; `az webapp restart` fixed it immediately. F1 tier, shared CPU.
Restart after each deploy and confirm the console renders before declaring it live.

**4. Refusal behaviour is unverified.** The two "unanswerable" trap questions cannot be tested in
mock mode (`MockChatModel` echoes retrieved chunks and never refuses), so mock `refusal_correct`
is 0.000 — that measures the mock, not the system. Needs a live adversarial run:
`python -m cli.eval run --sets adversarial` (real billed calls).

**5. `okf/` skeletons need their owners.** (The team's `okf/failure-modes/*.md` and
`okf/playbooks/*.md` have since landed on the branch - all 18 failure-mode slugs the service files
link to now resolve.) Every service file says `owned_by: "TBD - set in
review"`. The aliases are correct (generated from the corpus); `depends_on`, ownership and the
failure-mode lists need the owning SRE before merge. 17 service names still unclaimed —
`terraform`, `kafka`, `bgp`, `clickhouse`, `nsg`, `azure-vnet` and similar — each a genuine "does
this deserve a concept file?" call.

**6. `api/main.py` has no authentication**, and Chroma persists to container-local disk (no shared
state across instances, re-ingest on every redeploy). Both flagged, neither in scope for this pass.

---

## Out of scope for this pass

The agentic loop (decompose → multi-retrieve → self-check → structured RCA with 5-Whys), the rest
of the OKF layer (failure modes, playbooks, dependency graph), document-level ABAC, and moving
Chroma off container-local disk. Sequence those now that the eval harness can detect a regression.

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
