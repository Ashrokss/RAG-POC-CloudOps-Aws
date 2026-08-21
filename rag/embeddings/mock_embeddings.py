"""
A vector of random floats would make semantic retrieval indistinguishable from
noise, so any mock-vs-live comparison in the eval harness (e.g. "does semantic
search beat keyword search on paraphrased questions?") would be meaningless
until real Bedrock credentials exist. Hashing each token into a fixed
dimension with a hash-derived sign, instead of drawing random numbers, means
two texts sharing vocabulary always land closer in cosine-similarity space
than two texts that don't - a real, if crude, lexical signal that keeps
retrieval-strategy comparisons directionally meaningful in mock mode.
"""

from __future__ import annotations

import hashlib
import math
import re

from langchain_core.embeddings import Embeddings

_TOKEN_RE = re.compile(r"[a-z0-9]+")


class MockBedrockEmbeddings(Embeddings):
    def __init__(self, dimension: int = 256) -> None:
        self.dimension = dimension

    def embed_documents(self, texts: list[str]) -> list[list[float]]:
        return [self._embed(text) for text in texts]

    def embed_query(self, text: str) -> list[float]:
        return self._embed(text)

    def _embed(self, text: str) -> list[float]:
        vector = [0.0] * self.dimension
        for token in _TOKEN_RE.findall(text.lower()):
            digest = hashlib.sha256(token.encode("utf-8")).digest()
            index = int.from_bytes(digest[:4], "big") % self.dimension
            sign = 1.0 if digest[4] & 1 == 0 else -1.0
            vector[index] += sign

        norm = math.sqrt(sum(component * component for component in vector))
        if norm == 0.0:
            return vector
        return [component / norm for component in vector]
