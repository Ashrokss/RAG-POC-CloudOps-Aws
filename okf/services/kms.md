---
type: service
id: kms
name: AWS KMS
aliases: ["KMS", "key-management", "kms"]
depends_on: ["iam"]
owned_by: "TBD - set in review"
---

> Skeleton generated from the corpus inventory (`services:` frontmatter across
> `data/raw_rca_docs/`). The owning SRE must correct `owned_by`, `depends_on`,
> and the failure-mode list in PR review - curation is the point of this layer,
> the generator only guarantees the aliases actually seen in the corpus.


## What it is

Encryption key management. Its failures are permission failures on the key policy, surfacing as errors in whatever service was trying to decrypt.

## Known failure modes

- [Key policy blocking a replication or decrypt path](../failure-modes/config-regression.md) - seen in INC-2025-0302
