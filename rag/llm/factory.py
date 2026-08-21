"""
Every caller (rag_chain, eval/answer_quality, retrieval/rerank) imports
get_chat_model from here rather than from a specific provider module, so
flipping LLM_PROVIDER is a config change in .env, not a code change in every
one of those callers.
"""

from __future__ import annotations

from langchain_core.language_models.chat_models import BaseChatModel

from config.settings import get_settings


def get_chat_model() -> BaseChatModel:
    settings = get_settings()
    if settings.llm_provider == "bedrock":
        from rag.llm.bedrock_llm import get_chat_model as _get_chat_model
    else:
        from rag.llm.azure_llm import get_chat_model as _get_chat_model
    return _get_chat_model()
