"""
The prompt fixture reproduces the mock's own marker/header convention
(CONTEXT_MARKER, QUESTION_MARKER, the '[SOURCE: ...]' row) byte-for-byte
rather than importing a prompt-template helper, because that convention is
the module's documented contract - these tests are what pins it down.
"""

from __future__ import annotations

from langchain_core.messages import AIMessage, HumanMessage

from rag.llm.mock_chat_model import CONTEXT_MARKER, QUESTION_MARKER, MockChatModel


def _prompt(question: str) -> str:
    return (
        f"{CONTEXT_MARKER}\n"
        "[SOURCE: INC-2025-0001 · Summary]\n"
        "The database connection pool was exhausted during peak traffic.\n"
        f"{QUESTION_MARKER}\n"
        f"{question}"
    )


def test_invoke_returns_non_empty_answer_for_context_and_question() -> None:
    model = MockChatModel()

    response = model.invoke([HumanMessage(content=_prompt("What caused the incident?"))])

    assert isinstance(response, AIMessage)
    assert response.content
    assert "INC-2025-0001" in response.content
    assert "Summary" in response.content


def test_bind_tools_returns_tool_call_shaped_response() -> None:
    def get_incident_severity(incident_id: str) -> str:
        """Look up the severity level for a given incident id."""
        return "high"

    model = MockChatModel().bind_tools([get_incident_severity])

    response = model.invoke([HumanMessage(content="What is the severity of INC-2025-0001?")])

    assert isinstance(response, AIMessage)
    assert len(response.tool_calls) == 1
    tool_call = response.tool_calls[0]
    assert tool_call["name"] == "get_incident_severity"
    assert "incident_id" in tool_call["args"]
    assert tool_call["id"].startswith("call_")
