# RCA knowledge platform (v2)

A rebuild of the RAG POC around one idea: **the system's own refusal is the
signal that it should go and learn something**, and nothing it learns enters
the knowledge base without a named human approving it.

Independent of `rag/` — different store, different entry points, no shared
imports. Both can run side by side while v1 stays deployed.

## Three planes

| plane | contents | who writes | retrievable |
|---|---|---|---|
| **evidence** | RCA documents, chunked and embedded | ingest pipeline | yes |
| **concept** | approved knowledge cards, service vocabulary | humans, via review | yes |
| **candidate** | knowledge researched from outside, not yet approved | research agent | **no** |

The plane is a column, not a separate store, so promotion is an `UPDATE` plus
an audit row rather than a copy between systems that can half-fail. The
candidate plane is excluded from retrieval by default and must be asked for
explicitly — unpromoted knowledge cannot leak into an answer.

## The loop

```
question ──► route ──┬─► retrieval  (hybrid, capped at k)
                     ├─► aggregate  (SQL over the incident table + chunks)
                     └─► GAP  ──►  research (sanitised query, injected search)
                                     └─► candidate card (quarantined)
                                          └─► adversarial verifier
                                               ├─ quotes verbatim in source?
                                               ├─ vendor / official source?
                                               ├─ conflicts with what we know?
                                               └─ N voters, default reject
                                                    └─► HUMAN REVIEW
                                                         ├─ reject (reason required,
                                                         │   gap reopens)
                                                         └─ approve (named actor)
                                                              └─► knowledge/cards/*.md
                                                                   └─► indexed, gap resolved
```

Gap detection uses three signals, because one is not enough:

- **unknown_entity** — the question names an incident id the store has never
  seen. Exact, and it outranks everything: such a question *retrieves well*,
  since every incident id looks alike.
- **refused** — the model said it had insufficient evidence. The most
  trustworthy signal, and the reason refusal is a first-class outcome.
- **low_coverage** — top semantic score below the floor, *and* the answer cited
  nothing. A resolved citation outranks a similarity number.

## Commands

```bash
python -m rca.cli ingest --reset            # corpus + any approved cards
python -m rca.cli ask "<question>"          # routes, answers, opens a gap if it can't
python -m rca.cli gaps list                 # what the corpus can't answer, by hit count
python -m rca.cli gaps research <gap_id>    # research + verify -> candidate
python -m rca.cli review list               # the queue, with verifier reasoning
python -m rca.cli review approve <id> --actor you@example.com
python -m rca.cli review reject  <id> --actor you@example.com --reason "..."
python -m rca.cli rca INC-2025-0101         # structured RCA report
python -m rca.cli audit                     # who changed what the system believes
```

Runs fully offline: `HashEmbedder` and `EchoChatModel` are the defaults, and
the search backend returns nothing rather than inventing sources. Set
`AZURE_AI_ENDPOINT` / `AZURE_AI_KEY` / `AZURE_AI_EMBED_MODEL` / `OPENAI_MODEL`
to switch to real models.

## Decisions worth knowing

**SQLite now, Postgres+pgvector later.** The schema is written for the swap:
same tables, and the only backend-specific code is the brute-force cosine in
`Store.search_vectors`. At this size that is microseconds. One relational
store rather than a vector DB plus a database, because half the hard questions
here are SQL — "longest detection gap" is a max over a column — and the review
queue wants transactions.

**Deterministic ids everywhere.** `chunk_id = sha1(doc_id|section|ordinal)`,
`doc_id` from the source URI. Ingest is idempotent by construction; v1 minted
uuid4 per call and a second ingest silently duplicated the corpus.

**One embedding model per store, recorded.** `Store.embedding_models()` exists
so a mismatch is a loud failure rather than a dimension error surfacing in the
UI — or worse, silently comparable vectors that mean nothing.

**Outbound queries are sanitised, and it is tested.** `research.sanitise_query`
strips account ids, ARNs, subnet ids, internal hostnames, emails, IPs and
incident ids before anything reaches an external search API. Seven parametrised
tests cover it. "We'll remember not to paste chunks into the search box" is not
a control.

**The verifier fails cards; it does not bless them.** Its cheapest check is
mechanical — is the quote verbatim on the page it cites — because a model asked
"is this well supported?" says yes to almost anything. Voters default to
reject, and unverifiable is not the same as verified.

**RCA reports are typed, not prose.** Every field carries its own citations
(`evidence_map`), and fields the corpus could not support are named in
`unsupported_fields` rather than smoothed into fluent paragraphs. A generated
report re-enters the pipeline as a candidate — the system does not trust its
own output because it produced it.

## What is deliberately not built

Live web search (the interface is there; the paid backend is not), an agentic
plan/critique loop, a review UI beyond the CLI, and review-TTL expiry sweeps.
Each is a small addition to a working spine, and each is easier to justify once
there is a real distribution of gaps to look at — log gaps for a fortnight
before automating anything.
