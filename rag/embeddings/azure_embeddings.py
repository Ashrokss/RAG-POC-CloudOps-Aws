"""
No embedding deployment name has been provisioned alongside the Azure chat
credentials (AZURE_AI_EMBED_MODEL is blank), so embeddings stay on
MockBedrockEmbeddings even when the chat model is live. This is decoupled
from Settings.mock_mode on purpose - a working generation path shouldn't be
blocked on an embedding deployment nobody has provisioned yet, and the
eval harness still needs the mock's deliberately lexically-correlated
vectors to produce a meaningful semantic-vs-keyword comparison until one is.
"""

from __future__ import annotations

import logging
import re
import time

from langchain_core.embeddings import Embeddings

from config.settings import get_settings
from rag.embeddings.mock_embeddings import MockBedrockEmbeddings

logger = logging.getLogger(__name__)
_warned_missing_embed_model = False

# A single embed_documents(233 chunks) call against the S0 tier immediately hit
# RateLimitReached - one oversized request, not many small ones, tripped it -
# so requests are batched (bounding tokens-per-call) AND retried with backoff
# (bounding calls-per-minute). Azure's error message includes its own
# "retry after N seconds" hint, which is honored over a fixed backoff when
# present since it reflects the account's actual remaining throttle window.
_BATCH_SIZE = 20
_MAX_RETRIES = 6
_FALLBACK_BACKOFF_SECONDS = 10.0
_RETRY_AFTER_RE = re.compile(r"retry after (\d+) seconds", re.IGNORECASE)


class AzureAIEmbeddings(Embeddings):
    def __init__(self, endpoint: str, key: str) -> None:
        from azure.ai.inference import EmbeddingsClient
        from azure.core.credentials import AzureKeyCredential

        self._client = EmbeddingsClient(endpoint=endpoint, credential=AzureKeyCredential(key))

    def embed_documents(self, texts: list[str]) -> list[list[float]]:
        embeddings: list[list[float]] = []
        for start in range(0, len(texts), _BATCH_SIZE):
            batch = texts[start : start + _BATCH_SIZE]
            embeddings.extend(self._embed_batch_with_retry(batch))
        return embeddings

    def _embed_batch_with_retry(self, batch: list[str]) -> list[list[float]]:
        from azure.core.exceptions import HttpResponseError

        backoff = _FALLBACK_BACKOFF_SECONDS
        for attempt in range(1, _MAX_RETRIES + 1):
            try:
                response = self._client.embed(input=batch)
                return [item.embedding for item in response.data]
            except HttpResponseError as exc:
                is_rate_limit = getattr(exc, "status_code", None) == 429 or "RateLimitReached" in str(exc)
                if not is_rate_limit or attempt == _MAX_RETRIES:
                    raise
                match = _RETRY_AFTER_RE.search(str(exc))
                wait_seconds = float(match.group(1)) if match else backoff
                logger.warning(
                    "Azure embeddings rate limit hit (attempt %d/%d) - waiting %.0fs before retrying.",
                    attempt,
                    _MAX_RETRIES,
                    wait_seconds,
                )
                time.sleep(wait_seconds)
                backoff *= 2
        raise AssertionError("unreachable - loop above always returns or raises")

    def embed_query(self, text: str) -> list[float]:
        return self.embed_documents([text])[0]


def _build_endpoint(base_endpoint: str, model: str) -> str:
    base = base_endpoint.rstrip("/")
    if "cognitiveservices.azure.com" in base and "/openai/deployments/" not in base:
        return f"{base}/openai/deployments/{model}"
    return base


def get_embeddings() -> Embeddings:
    global _warned_missing_embed_model
    settings = get_settings()

    if settings.mock_mode or not settings.azure_ai_embed_model:
        if not settings.mock_mode and not _warned_missing_embed_model:
            logger.warning(
                "AZURE_AI_EMBED_MODEL is not set - embeddings stay on the mock "
                "implementation even though the Azure chat model is live."
            )
            _warned_missing_embed_model = True
        return MockBedrockEmbeddings()

    endpoint = _build_endpoint(settings.azure_ai_endpoint, settings.azure_ai_embed_model)
    return AzureAIEmbeddings(endpoint=endpoint, key=settings.azure_ai_key)
