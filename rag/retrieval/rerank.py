"""
langchain_aws is only imported inside the 'bedrock_cohere' branch, mirroring
rag/llm/bedrock_llm.py, so a machine without that optional dependency
installed can still use the 'llm' and 'none' rerank paths (and every other
retrieval strategy, none of which touch this branch at all).

The 'none'/unrecognized-provider branch never passes the base retriever
straight through, in mock OR live mode. It used to (live + 'none' returned
base_retriever untouched) - a live bake-off against the deployed app found
that base_retriever is the k*2-wide hybrid ensemble built by
rag/retrieval/factory.py's hybrid_rerank case, and EnsembleRetriever doesn't
cap its own fused output to that k*2 either, so a top_n=10 request was
silently sending 34 chunks into the generation prompt - the "hybrid_rerank"
name is a promise of at most top_n documents regardless of which reranker
(if any) is configured, and "no paid reranker configured" should mean
"re-score for free and truncate", not "skip truncating too". The deterministic
keyword-overlap re-scorer below is that free fallback - it also happens to be
what already ran in mock mode (mock_mode's own branch used it before this
fix collapsed the two into one), so mock-mode behavior is unchanged.

The 'llm' scoring prompt spells the scale out as words ("zero" / "ten")
rather than digits: MockChatModel echoes the prompt it was given back into
its reply when the reply doesn't otherwise match its expected format, so
digit literals in the prompt itself would show up as a constant, meaningless
"relevance score" for every document under mock mode.
"""

from __future__ import annotations

import re
from collections.abc import Sequence

from langchain_classic.retrievers import ContextualCompressionRetriever
from langchain_core.callbacks import Callbacks
from langchain_core.documents import Document
from langchain_core.documents.compressor import BaseDocumentCompressor
from langchain_core.language_models.chat_models import BaseChatModel
from langchain_core.retrievers import BaseRetriever

from config.settings import get_settings
from rag.llm.factory import get_chat_model

_STOPWORDS = {
    "a", "an", "and", "are", "as", "at", "be", "by", "for", "from", "has",
    "have", "how", "in", "into", "is", "it", "its", "of", "on", "or", "that",
    "the", "this", "to", "was", "were", "what", "when", "where", "which",
    "why", "will", "with",
}

_NUMBER_RE = re.compile(r"\d+(?:\.\d+)?")
_TOKEN_RE = re.compile(r"[a-z0-9]+")


def _tokenize(text: str) -> set[str]:
    return {token for token in _TOKEN_RE.findall(text.lower()) if token not in _STOPWORDS}


class _LLMRelevanceCompressor(BaseDocumentCompressor):
    top_n: int

    def compress_documents(
        self,
        documents: Sequence[Document],
        query: str,
        callbacks: Callbacks | None = None,
    ) -> Sequence[Document]:
        chat_model = get_chat_model()
        ranked = sorted(documents, key=lambda doc: self._score(chat_model, query, doc), reverse=True)
        return ranked[: self.top_n]

    @staticmethod
    def _score(chat_model: BaseChatModel, query: str, doc: Document) -> float:
        prompt = (
            "Rate how relevant the document is to the query on a scale from "
            "zero to ten, where ten is most relevant. Reply with only the "
            "number.\n\n"
            f"Query: {query}\n\n"
            f"Document: {doc.page_content}"
        )
        response = chat_model.invoke(prompt)
        content = response.content if isinstance(response.content, str) else str(response.content)
        matches = _NUMBER_RE.findall(content)
        return float(matches[-1]) if matches else 0.0


class _KeywordOverlapCompressor(BaseDocumentCompressor):
    top_n: int

    def compress_documents(
        self,
        documents: Sequence[Document],
        query: str,
        callbacks: Callbacks | None = None,
    ) -> Sequence[Document]:
        query_tokens = _tokenize(query)
        ranked = sorted(
            documents,
            key=lambda doc: len(query_tokens & _tokenize(doc.page_content)),
            reverse=True,
        )
        return ranked[: self.top_n]


def get_reranked_retriever(base_retriever: BaseRetriever, provider: str, top_n: int = 5) -> BaseRetriever:
    if provider == "bedrock_cohere":
        from langchain_aws import BedrockRerank

        settings = get_settings()
        compressor: BaseDocumentCompressor = BedrockRerank(
            model_id=settings.bedrock_rerank_model_id,
            region_name=settings.aws_region,
            top_n=top_n,
        )
    elif provider == "llm":
        compressor = _LLMRelevanceCompressor(top_n=top_n)
    else:
        # provider == "none" or anything unrecognized - still enforce the
        # top_n contract (see module docstring), live or mock.
        compressor = _KeywordOverlapCompressor(top_n=top_n)

    return ContextualCompressionRetriever(base_compressor=compressor, base_retriever=base_retriever)
