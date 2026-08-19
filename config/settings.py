"""
Every other module in this codebase imports get_settings() rather than
constructing Settings() or reading os.environ directly, so the mock/live
decision - and the one-time warning that goes with it - happens exactly once
per process, no matter how many modules need config.

The mock-mode resolution deliberately checks boto3.Session().get_credentials()
instead of just testing whether AWS_ACCESS_KEY_ID is a non-empty string:
get_credentials() also picks up ~/.aws/credentials, SSO profiles, and
instance-role credentials, none of which show up as env vars. It reads
already-cached local state and never makes a network call, so it's safe to
run unconditionally even before real AWS credentials exist.
"""

from __future__ import annotations

import logging
from functools import lru_cache
from typing import Literal, Optional

from dotenv import load_dotenv
from pydantic import Field, PrivateAttr
from pydantic_settings import BaseSettings, SettingsConfigDict

# Populates os.environ from .env (without clobbering real exported vars) so
# boto3's own credential chain and this Settings model see the same values -
# pydantic-settings' env_file loading below only fills Settings fields, it
# doesn't touch os.environ, and boto3 only ever looks at os.environ.
load_dotenv(override=False)

logger = logging.getLogger(__name__)

_TRUE_VALUES = {"true", "1", "yes"}
_FALSE_VALUES = {"false", "0", "no"}


class Settings(BaseSettings):
    model_config = SettingsConfigDict(env_file=".env", env_file_encoding="utf-8", extra="ignore")

    llm_provider: Literal["azure", "bedrock"] = Field(default="azure", alias="LLM_PROVIDER")

    aws_region: str = Field(default="us-east-1", alias="AWS_REGION")
    aws_access_key_id: Optional[str] = Field(default=None, alias="AWS_ACCESS_KEY_ID")
    aws_secret_access_key: Optional[str] = Field(default=None, alias="AWS_SECRET_ACCESS_KEY")
    aws_session_token: Optional[str] = Field(default=None, alias="AWS_SESSION_TOKEN")

    bedrock_mock_mode_raw: Optional[str] = Field(default=None, alias="BEDROCK_MOCK_MODE")
    bedrock_chat_model_id: str = Field(default="anthropic.claude-sonnet-5", alias="BEDROCK_CHAT_MODEL_ID")
    bedrock_embed_model_id: str = Field(default="amazon.titan-embed-text-v2:0", alias="BEDROCK_EMBED_MODEL_ID")
    bedrock_rerank_model_id: str = Field(default="cohere.rerank-v3-5:0", alias="BEDROCK_RERANK_MODEL_ID")

    # AD service principal - not consumed by any provider yet (the clients
    # below use key auth); reserved for a future AD-token auth path.
    azure_tenant_id: Optional[str] = Field(default=None, alias="AZURE_TENANT_ID")
    azure_client_id: Optional[str] = Field(default=None, alias="AZURE_CLIENT_ID")
    azure_client_secret: Optional[str] = Field(default=None, alias="AZURE_CLIENT_SECRET")

    azure_mock_mode_raw: Optional[str] = Field(default=None, alias="AZURE_MOCK_MODE")
    azure_ai_endpoint: Optional[str] = Field(default=None, alias="AZURE_AI_ENDPOINT")
    azure_ai_key: Optional[str] = Field(default=None, alias="AZURE_AI_KEY")
    # Two possible sources for the chat deployment name, in priority order -
    # AZURE_AI_CHAT_MODEL is the clearer name, OPENAI_MODEL is what a .env
    # copied from CloudOps-AWS's other services is likely to already contain.
    azure_ai_chat_model_raw: Optional[str] = Field(default=None, alias="AZURE_AI_CHAT_MODEL")
    openai_model_raw: Optional[str] = Field(default=None, alias="OPENAI_MODEL")
    # No embedding deployment name means embeddings stay mocked even when the
    # chat model is live - see rag/embeddings/azure_embeddings.py.
    azure_ai_embed_model: Optional[str] = Field(default=None, alias="AZURE_AI_EMBED_MODEL")

    rerank_provider: Literal["none", "bedrock_cohere", "llm"] = Field(default="none", alias="RERANK_PROVIDER")

    chroma_persist_dir: str = Field(default="./data/chroma_db", alias="CHROMA_PERSIST_DIR")
    chroma_collection_name: str = Field(default="rca_docs", alias="CHROMA_COLLECTION_NAME")

    chunk_size: int = Field(default=800, alias="CHUNK_SIZE")
    chunk_overlap: int = Field(default=120, alias="CHUNK_OVERLAP")
    retrieval_top_k: int = Field(default=5, alias="RETRIEVAL_TOP_K")

    eval_judge_provider: Literal["heuristic", "llm"] = Field(default="heuristic", alias="EVAL_JUDGE_PROVIDER")

    _mock_mode: bool = PrivateAttr()

    def model_post_init(self, __context: object) -> None:
        self._mock_mode = self._resolve_bedrock_mock_mode() if self.llm_provider == "bedrock" else self._resolve_azure_mock_mode()

    def _resolve_bedrock_mock_mode(self) -> bool:
        raw = (self.bedrock_mock_mode_raw or "").strip().lower()
        if raw in _TRUE_VALUES:
            return True
        if raw in _FALSE_VALUES:
            return False

        # No explicit override (or an unrecognized value) - auto-detect from
        # whatever credential sources boto3 already knows about. Imported here
        # rather than at module load, same reasoning as rag/llm/bedrock_llm.py:
        # a deployment running LLM_PROVIDER=azure shouldn't need boto3 installed
        # at all, since this branch never runs for it.
        import boto3

        has_credentials = boto3.Session().get_credentials() is not None
        if not has_credentials:
            logger.warning(
                "No AWS credentials found and BEDROCK_MOCK_MODE is unset - "
                "falling back to mock mode. Set BEDROCK_MOCK_MODE=false once "
                "real credentials are configured to use live Bedrock."
            )
            return True
        return False

    def _resolve_azure_mock_mode(self) -> bool:
        raw = (self.azure_mock_mode_raw or "").strip().lower()
        if raw in _TRUE_VALUES:
            return True
        if raw in _FALSE_VALUES:
            return False

        has_credentials = bool(self.azure_ai_endpoint and self.azure_ai_key)
        if not has_credentials:
            logger.warning(
                "AZURE_AI_ENDPOINT/AZURE_AI_KEY not fully set and AZURE_MOCK_MODE "
                "is unset - falling back to mock mode. Set AZURE_MOCK_MODE=false "
                "once real credentials are configured to use live Azure AI."
            )
            return True
        return False

    @property
    def mock_mode(self) -> bool:
        return self._mock_mode

    @property
    def azure_ai_chat_model(self) -> str:
        return self.azure_ai_chat_model_raw or self.openai_model_raw or "gpt-4o-mini"


@lru_cache(maxsize=1)
def get_settings() -> Settings:
    return Settings()
