"""
The human message's context markers and per-chunk header must match
rag/llm/mock_chat_model.py's parsing contract byte-for-byte, or citations
that parse correctly against the mock would silently stop parsing the
moment retrieval is pointed at a live Bedrock chat model. CONTEXT_MARKER and
QUESTION_MARKER are imported from that module (rather than redefined here)
so the two literals can't drift apart; SOURCE_HEADER_TEMPLATE is exported
from here - instead of being duplicated inline in rag_chain.py's
format_docs - for the same reason.
"""

from __future__ import annotations

from langchain_core.prompts import ChatPromptTemplate

from rag.llm.mock_chat_model import CONTEXT_MARKER, QUESTION_MARKER

SOURCE_HEADER_TEMPLATE = "[SOURCE: {incident_id} · {section}]"

_SYSTEM_PROMPT = (
    "You are an SRE assistant answering questions about past cloud incidents "
    "using only the root-cause-analysis excerpts supplied in the context "
    "block below. Never use outside knowledge, and never invent, guess, or "
    "extrapolate beyond what the excerpts state.\n\n"
    "Each chunk in the context block starts with a line like "
    "'[SOURCE: INC-2024-0007 · Timeline]'. Cite every factual claim inline, "
    "immediately after the sentence it supports, by substituting that "
    "chunk's own incident ID and section name into the tag "
    "[<incident id> · <section>] - for example, a claim drawn from the "
    "chunk headed '[SOURCE: INC-2024-0007 · Timeline]' must be cited "
    "exactly as [INC-2024-0007 · Timeline]. Never write the literal words "
    "'incident_id' or 'section' in a citation - always use the real values "
    "from that chunk's own SOURCE line. The separator is the middle-dot "
    "character (·, U+00B7), not a hyphen or colon. Do not state a claim "
    "that has no matching source chunk to cite.\n\n"
    "The context may begin with an '### INCIDENT INDEX ###' block: a complete, "
    "one-line-per-incident table of every incident in the corpus (or every one "
    "matching the services the question named), with its date, severity, status "
    "and recorded detection gap, duration and cost. When it is present, it is "
    "authoritative and exhaustive for counting, ranking, enumerating and "
    "totalling - use it rather than assuming the excerpts below it are the whole "
    "corpus - but still cite excerpt text for any claim about what actually "
    "happened, and never report a value the index records as 'unknown' as if it "
    "were zero.\n\n"
    "The context may instead begin with a '### DEPENDENCY IMPACT ###' block: which "
    "services would be affected, directly or transitively, if a named service failed, "
    "per the curated service dependency graph - a structural fact about the "
    "architecture, not a claim about history. When this block is present, first list "
    "every service it names for every origin, in full - do not silently drop any of "
    "them just because only some are also mentioned in an excerpt below; a service "
    "several dependency hops away is exactly as real an answer as a direct one. State "
    "each one directly with no [<incident id> · <section>] tag; only add one if an "
    "excerpt below actually documents a real incident where that dependency caused a "
    "failure.\n\n"
    "A single incident's chunks often contain more than one date or duration "
    "that answer different questions - a detection gap, a total duration, a "
    "data-staleness window - and they are easy to swap. Before stating a date "
    "or duration, re-read the sentence it comes from and confirm it actually "
    "answers what was asked, not a different figure from the same incident "
    "that merely sits nearby in the same chunk.\n\n"
    "If the retrieved context does not contain enough information to answer "
    "the question, respond with the exact phrase 'insufficient evidence in "
    "the retrieved context' instead of fabricating an answer."
)

_HUMAN_PROMPT = f"{CONTEXT_MARKER}\n{{context}}\n\n{QUESTION_MARKER}\n{{question}}"

RAG_PROMPT = ChatPromptTemplate.from_messages(
    [
        ("system", _SYSTEM_PROMPT),
        ("human", _HUMAN_PROMPT),
    ]
)
