"""
Wraps azure.ai.inference.ChatCompletionsClient directly rather than a
LangChain Azure AI integration package. The endpoint-shaping below (append
/openai/deployments/{model} for a bare cognitiveservices.azure.com host,
omitting the model= argument on the resulting call) is copied from
CloudOps-AWS's backend-agent/utils/model_client.py - the one component
already proven to work against this exact class of Azure AI Foundry
resource - rather than trusting an unfamiliar integration's own endpoint
convention against a resource this codebase hasn't talked to before.
"""

from __future__ import annotations

import json
from typing import Any, Optional

from langchain_core.callbacks import CallbackManagerForLLMRun
from langchain_core.language_models.chat_models import BaseChatModel
from langchain_core.messages import AIMessage, BaseMessage
from langchain_core.outputs import ChatGeneration, ChatResult
from langchain_core.utils.function_calling import convert_to_openai_tool

from config.settings import get_settings

_ROLE_MAP = {"human": "user", "ai": "assistant", "system": "system"}


def _build_client(endpoint: str, key: str, model: str):
    from azure.ai.inference import ChatCompletionsClient
    from azure.core.credentials import AzureKeyCredential

    base = endpoint.rstrip("/")
    if "cognitiveservices.azure.com" in base and "/openai/deployments/" not in base:
        client = ChatCompletionsClient(endpoint=f"{base}/openai/deployments/{model}", credential=AzureKeyCredential(key))
        return client, False
    return ChatCompletionsClient(endpoint=base, credential=AzureKeyCredential(key)), True


def _to_azure_message(message: BaseMessage) -> dict:
    content = message.content if isinstance(message.content, str) else str(message.content)
    return {"role": _ROLE_MAP.get(message.type, "user"), "content": content}


class AzureAIChatModel(BaseChatModel):
    endpoint: str
    key: str
    model: str
    temperature: float = 0.1

    @property
    def _llm_type(self) -> str:
        return "azure-ai-inference-chat"

    def bind_tools(self, tools: list[Any], **kwargs: Any) -> Any:
        formatted_tools = [convert_to_openai_tool(tool) for tool in tools]
        return super().bind(tools=formatted_tools, **kwargs)

    def _generate(
        self,
        messages: list[BaseMessage],
        stop: Optional[list[str]] = None,
        run_manager: Optional[CallbackManagerForLLMRun] = None,
        **kwargs: Any,
    ) -> ChatResult:
        client, include_model_arg = _build_client(self.endpoint, self.key, self.model)
        payload: dict[str, Any] = {
            "messages": [_to_azure_message(m) for m in messages],
            "temperature": self.temperature,
        }
        if include_model_arg:
            payload["model"] = self.model
        tools = kwargs.get("tools")
        if tools:
            payload["tools"] = tools

        response = client.complete(**payload)
        choice = response.choices[0]
        azure_tool_calls = getattr(choice.message, "tool_calls", None)

        if azure_tool_calls:
            tool_calls = [
                {
                    "name": call.function.name,
                    "args": json.loads(call.function.arguments) if call.function.arguments else {},
                    "id": call.id,
                    "type": "tool_call",
                }
                for call in azure_tool_calls
            ]
            message = AIMessage(content=choice.message.content or "", tool_calls=tool_calls)
        else:
            message = AIMessage(content=choice.message.content or "")
        return ChatResult(generations=[ChatGeneration(message=message)])


def get_chat_model() -> BaseChatModel:
    settings = get_settings()
    if settings.mock_mode:
        from rag.llm.mock_chat_model import MockChatModel

        return MockChatModel()

    return AzureAIChatModel(
        endpoint=settings.azure_ai_endpoint,
        key=settings.azure_ai_key,
        model=settings.azure_ai_chat_model,
    )
