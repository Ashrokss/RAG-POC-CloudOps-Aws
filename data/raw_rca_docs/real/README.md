# Real RCA docs

Place your own RCA docs here as markdown following `docs/rca_doc_template.md`, or share them with
the assistant to have them normalized into this format. This folder is empty right now; ingestion
works fine with zero files here.

Note for whoever builds the ingestion loader (a later, separate task): this file itself does not
match the RCA doc pattern (no YAML frontmatter, no `## Summary` / `## Timeline` / etc. sections) and
must not be parsed as an RCA doc. The loader should skip this `README.md` - and anything else in
`data/raw_rca_docs/` that doesn't match the RCA doc pattern - rather than failing or misparsing it.
