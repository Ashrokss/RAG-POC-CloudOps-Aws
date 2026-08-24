"""
Embeddings and chat behind two functions, with deterministic offline defaults.

The mock embedder hashes tokens into a fixed dimension with a hash-derived
sign, so two texts sharing vocabulary land closer than two that do not. That
is a crude but real lexical signal, which keeps retrieval comparisons
meaningful before any credentials exist - random vectors would make every
offline evaluation noise.

embedding_model_id() is stamped into every chunk row at write time. Vectors
from two models are not comparable and usually not even the same length; the
predecessor shipped a mock-built index into an app querying with a real model
and surfaced it as "expecting dimension 256, got 1536", once per strategy, in
the UI. Worse is when the dimensions happen to match and it returns confident
nonsense instead.

load_dotenv() runs at import time because this module reads os.getenv()
directly and rca/ is deliberately independent of rag/'s config.settings (the
only other place in the repo that loads .env). Without this, a standalone
`python -m rca.cli ask/ingest/...` - exactly what this project's own docs
tell you to run - silently fell back to the mock embedder/chat model with no
warning whenever nothing else had already imported config.settings first in
the same process. override=False for the same reason config/settings.py
uses it: never clobber a real env var the shell already set.
"""

from __future__ import annotations

import hashlib
import math
import os
import re
from typing import Protocol

from dotenv import load_dotenv

load_dotenv(override=False)

_TOKEN_RE = re.compile(r"[a-z0-9]+")


class Embedder(Protocol):
    model_id: str

    def embed(self, texts: list[str]) -> list[list[float]]: ...


class ChatModel(Protocol):
    model_id: str

    def complete(self, system: str, user: str) -> str: ...


class HashEmbedder:
    model_id = "mock:hash-256"

    def __init__(self, dimension: int = 256) -> None:
        self.dimension = dimension

    def embed(self, texts: list[str]) -> list[list[float]]:
        return [self._one(text) for text in texts]

    def _one(self, text: str) -> list[float]:
        vector = [0.0] * self.dimension
        for token in _TOKEN_RE.findall(text.lower()):
            digest = hashlib.sha256(token.encode("utf-8")).digest()
            vector[int.from_bytes(digest[:4], "big") % self.dimension] += (
                1.0 if digest[4] & 1 == 0 else -1.0
            )
        norm = math.sqrt(sum(v * v for v in vector))
        return vector if norm == 0 else [v / norm for v in vector]


class EchoChatModel:
    """Deterministic stand-in. It quotes the context back with citation tags so
    citation parsing, grounding and the report builder are all exercisable
    offline - it cannot reason, and no test should pretend otherwise."""

    model_id = "mock:echo"

    def complete(self, system: str, user: str) -> str:
        sources = re.findall(r"\[SOURCE: ([^\]]+)\]\n(.+?)(?=\n\[SOURCE:|\Z)", user, re.S)
        if not sources:
            return "insufficient evidence in the retrieved context"
        lines = [f"Synthesised from {len(sources)} chunk(s):"]
        for tag, body in sources[:3]:
            lines.append(f'"{" ".join(body.split())[:180]}" [{tag}]')
        return "\n".join(lines)


class AzureChatModel:
    def __init__(self, endpoint: str, key: str, deployment: str) -> None:
        from azure.ai.inference import ChatCompletionsClient
        from azure.core.credentials import AzureKeyCredential

        base = endpoint.rstrip("/")
        if "cognitiveservices.azure.com" in base and "/openai/deployments/" not in base:
            base = f"{base}/openai/deployments/{deployment}"
        self._client = ChatCompletionsClient(endpoint=base, credential=AzureKeyCredential(key))
        self.model_id = f"azure:{deployment}"

    def complete(self, system: str, user: str) -> str:
        response = self._client.complete(
            messages=[{"role": "system", "content": system}, {"role": "user", "content": user}],
            temperature=0.1,
        )
        return response.choices[0].message.content or ""


class AzureEmbedder:
    # Batched because a single embed_documents call over a few hundred chunks
    # tripped RateLimitReached on an S0 tier: one oversized request, not many
    # small ones.
    BATCH = 16

    def __init__(self, endpoint: str, key: str, deployment: str) -> None:
        from azure.ai.inference import EmbeddingsClient
        from azure.core.credentials import AzureKeyCredential

        base = endpoint.rstrip("/")
        if "cognitiveservices.azure.com" in base and "/openai/deployments/" not in base:
            base = f"{base}/openai/deployments/{deployment}"
        self._client = EmbeddingsClient(endpoint=base, credential=AzureKeyCredential(key))
        self.model_id = f"azure:{deployment}"

    def embed(self, texts: list[str]) -> list[list[float]]:
        out: list[list[float]] = []
        for start in range(0, len(texts), self.BATCH):
            response = self._client.embed(input=texts[start : start + self.BATCH])
            out.extend(item.embedding for item in response.data)
        return out


def get_embedder() -> Embedder:
    endpoint, key = os.getenv("AZURE_AI_ENDPOINT"), os.getenv("AZURE_AI_KEY")
    deployment = os.getenv("AZURE_AI_EMBED_MODEL")
    if endpoint and key and deployment:
        return AzureEmbedder(endpoint, key, deployment)
    return HashEmbedder()


def get_chat_model() -> ChatModel:
    endpoint, key = os.getenv("AZURE_AI_ENDPOINT"), os.getenv("AZURE_AI_KEY")
    deployment = os.getenv("AZURE_AI_CHAT_MODEL") or os.getenv("OPENAI_MODEL")
    if endpoint and key and deployment:
        return AzureChatModel(endpoint, key, deployment)
    return EchoChatModel()
