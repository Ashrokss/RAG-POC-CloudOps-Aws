"""
An LLM-judge or citation-parsing pass built against this mock has nothing to
grep for unless the mock's output format is nailed down in one place, so the
two marker conventions it relies on are fixed here and must be produced
byte-for-byte the same way by the prompt template:

1. Context-chunk header, one per retrieved chunk, on its own line inside the
   block the prompt places between the literal markers '### CONTEXT ###' and
   '### QUESTION ###':

       [SOURCE: <incident_id> · <section>]

   (· is U+00B7 MIDDLE DOT - not a hyphen or colon, so it can't collide
   with punctuation that might appear inside an incident_id or section name.)
   Everything between one header and the next (or the '### QUESTION ###'
   marker) is that chunk's text.

2. Citation tag emitted in the generated answer, wherever a chunk is quoted:

       [<incident_id> · <section>]

   Same field order and separator as the header, minus the 'SOURCE: ' prefix.
   Downstream citation-parsing can use one regex - r"\\[([^\\]·]+)·([^\\]]+)\\]"
   applied to the answer text - to recover (incident_id, section) pairs from
   both this mock and, eventually, live-model output that's asked to follow
   the same convention.

Tool-call handling exists only so a later LLM-judge pipeline (which invokes
the chat model with bind_tools/tools to get a structured verdict) doesn't
crash when pointed at mock mode before real Bedrock credentials exist - the
returned arguments are placeholders, not judgments.
"""

from __future__ import annotations

import re
import uuid
from typing import Any, Optional

from langchain_core.callbacks import CallbackManagerForLLMRun
from langchain_core.language_models.chat_models import BaseChatModel
from langchain_core.messages import AIMessage, BaseMessage
from langchain_core.outputs import ChatGeneration, ChatResult
from langchain_core.utils.function_calling import convert_to_openai_tool

CONTEXT_MARKER = "### CONTEXT ###"
QUESTION_MARKER = "### QUESTION ###"

_SOURCE_HEADER_RE = re.compile(
    r"^\[SOURCE:\s*(?P<incident_id>[^·\]]+?)\s*·\s*(?P<section>[^\]]+?)\]\s*$",
    re.MULTILINE,
)

_MAX_QUOTED_CHUNKS = 3
_SNIPPET_LENGTH = 200


def _placeholder_for_json_type(schema: dict[str, Any]) -> Any:
    json_type = schema.get("type", "string")
    if json_type == "string":
        enum = schema.get("enum")
        return enum[0] if enum else "mock-value"
    if json_type == "integer":
        return 0
    if json_type == "number":
        return 0.0
    if json_type == "boolean":
        return True
    if json_type == "array":
        return []
    if json_type == "object":
        return {}
    return "mock-value"


class MockChatModel(BaseChatModel):
    @property
    def _llm_type(self) -> str:
        return "mock-bedrock-chat"

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
        tools = kwargs.get("tools")
        if tools:
            message: AIMessage = self._mock_tool_call(tools[0])
        else:
            message = AIMessage(content=self._mock_answer(messages))
        return ChatResult(generations=[ChatGeneration(message=message)])

    def _mock_tool_call(self, tool_schema: dict[str, Any]) -> AIMessage:
        function = tool_schema.get("function", tool_schema)
        name = function.get("name", "mock_tool")
        parameters = function.get("parameters") or {}
        properties = parameters.get("properties") or {}
        required = parameters.get("required") or list(properties.keys())

        args = {field: _placeholder_for_json_type(properties.get(field, {})) for field in required}
        tool_call = {
            "name": name,
            "args": args,
            "id": f"call_{uuid.uuid4().hex[:8]}",
            "type": "tool_call",
        }
        return AIMessage(content="", tool_calls=[tool_call])

    def _mock_answer(self, messages: list[BaseMessage]) -> str:
        content = self._last_human_content(messages)
        context_block, question = self._split_context_and_question(content)
        chunks = self._parse_source_chunks(context_block)

        if not chunks:
            return f"[mock-bedrock-chat] no context markers found; question: {question or content}"

        lines = [f"Mock answer synthesized from {len(chunks)} retrieved chunk(s):"]
        for incident_id, section, text in chunks[:_MAX_QUOTED_CHUNKS]:
            snippet = " ".join(text.split())[:_SNIPPET_LENGTH]
            lines.append(f'"{snippet}" [{incident_id} · {section}]')
        if question:
            lines.append(f"(question: {question})")
        return "\n".join(lines)

    def _last_human_content(self, messages: list[BaseMessage]) -> str:
        for message in reversed(messages):
            if message.type == "human":
                content = message.content
                return content if isinstance(content, str) else str(content)
        return ""

    def _split_context_and_question(self, content: str) -> tuple[str, str]:
        context_start = content.find(CONTEXT_MARKER)
        question_start = content.find(QUESTION_MARKER)
        if context_start == -1 or question_start == -1:
            return "", content.strip()

        context_block = content[context_start + len(CONTEXT_MARKER) : question_start]
        question = content[question_start + len(QUESTION_MARKER) :].strip()
        return context_block, question

    def _parse_source_chunks(self, context_block: str) -> list[tuple[str, str, str]]:
        headers = list(_SOURCE_HEADER_RE.finditer(context_block))
        chunks = []
        for i, header in enumerate(headers):
            start = header.end()
            end = headers[i + 1].start() if i + 1 < len(headers) else len(context_block)
            text = context_block[start:end].strip()
            chunks.append((header.group("incident_id").strip(), header.group("section").strip(), text))
        return chunks
