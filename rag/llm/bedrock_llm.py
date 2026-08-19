"""
langchain_aws pulls in boto3 model clients that aren't needed for local mock
runs, so it's imported inside the live branch rather than at module load time
- a dev machine with no AWS extras installed can still `import` this module
and run the whole pipeline in mock mode.
"""

from __future__ import annotations

from langchain_core.language_models.chat_models import BaseChatModel

from config.settings import get_settings
from rag.llm.mock_chat_model import MockChatModel


def get_chat_model() -> BaseChatModel:
    settings = get_settings()
    if settings.mock_mode:
        return MockChatModel()

    from langchain_aws import ChatBedrockConverse

    return ChatBedrockConverse(
        model=settings.bedrock_chat_model_id,
        region_name=settings.aws_region,
        temperature=0.1,
    )
