"""
langchain_aws pulls in boto3 model clients that aren't needed for local mock
runs, so it's imported inside the live branch rather than at module load time
- a dev machine with no AWS extras installed can still `import` this module
and run the whole pipeline in mock mode.
"""

from __future__ import annotations

from langchain_core.embeddings import Embeddings

from config.settings import get_settings
from rag.embeddings.mock_embeddings import MockBedrockEmbeddings


def get_embeddings() -> Embeddings:
    settings = get_settings()
    if settings.mock_mode:
        return MockBedrockEmbeddings()

    from langchain_aws import BedrockEmbeddings

    return BedrockEmbeddings(
        model_id=settings.bedrock_embed_model_id,
        region_name=settings.aws_region,
    )
