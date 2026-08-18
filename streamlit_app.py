"""
Minimal interactive UI over the RAG chain, for manually testing retrieval-strategy
quality without going through the CLI or writing a Python one-liner.

Calls retrieve_for_question()/generate() directly rather than the
answer_question() wrapper, so retrieval happens exactly once per strategy per
question - each call is a real, rate-limited Azure API request in live mode, so
this UI must not silently double it just to also display the raw retrieved
chunks. It goes through retrieve_for_question rather than retrieve_only so the
console takes the same route (retrieval or aggregate) the API and the eval
harness take, and shows which one ran.

Launch from the repo root (sys.path[0] must be the repo root for the absolute
`from config...`/`from rag...` imports below to resolve): streamlit run streamlit_app.py
"""

from __future__ import annotations

import time
from pathlib import Path

import streamlit as st

from config.settings import get_settings
from eval.golden_schema import load_golden_questions
from rag.chain.rag_chain import generate, retrieve_for_question
from rag.retrieval.factory import STRATEGIES

st.set_page_config(page_title="RAG SRE Agent - Test Console", page_icon="🛠️", layout="wide")
st.title("RAG SRE Agent - Test Console")


def _escape_markdown_math(text: str) -> str:
    # st.write()/st.markdown() render "$...$" as LaTeX - a live bake-off
    # found every dollar-amount answer (e.g. "$20,700") rendered as mangled
    # equation glyphs the moment a second "$" appeared later in the text.
    return text.replace("$", "\\$")


@st.cache_data(show_spinner=False)
def _cached_answer(question: str, strategy: str, k: int):
    # Keyed on (question, strategy, k) only - provider/model/index are fixed
    # for this process's lifetime, and a redeploy (which restarts the
    # process) is what invalidates this in-memory cache. Without this, a
    # live bake-off found the same question re-submitted re-ran full,
    # billed Azure calls every time.
    start = time.perf_counter()
    docs, index_block, route = retrieve_for_question(question, strategy, k)
    answer, citations = generate(question, docs, index_block)
    latency_ms = (time.perf_counter() - start) * 1000
    return answer, citations, latency_ms, docs, route

settings = get_settings()

with st.sidebar:
    st.subheader("Environment")
    st.write(f"Provider: `{settings.llm_provider}`")
    st.write("Mode:", "🟢 live" if not settings.mock_mode else "🟡 mock")
    if settings.llm_provider == "azure":
        st.write(f"Chat model: `{settings.azure_ai_chat_model}`")
        st.write(f"Embed model: `{settings.azure_ai_embed_model or 'mock (none configured)'}`")
    st.divider()
    try:
        from rag.embeddings.factory import get_embeddings
        from rag.vectorstore.chroma_store import get_collection_stats, get_vectorstore

        stats = get_collection_stats(get_vectorstore(get_embeddings()))
        st.write(f"Indexed chunks: **{stats['count']}**")
    except Exception as exc:  # collection may not be built yet
        st.warning(f"Run `python -m cli.ingest run --reset` first.\n\n{exc}")

golden_path = Path("data/golden_qa/golden_qa.yaml")
sample_questions: list[str] = []
if golden_path.exists():
    try:
        sample_questions = [q.question for q in load_golden_questions(golden_path)]
    except Exception:
        pass  # golden set is optional - the console still works without it

picked = st.selectbox("Pick a golden question (optional)", ["(type your own)"] + sample_questions)
question = st.text_area("Question", value="" if picked == "(type your own)" else picked, height=80)

_STRATEGY_LABELS = {"keyword": "keyword (diagnostic only - see hybrid instead)"}


def _label_strategy(name: str) -> str:
    return _STRATEGY_LABELS.get(name, name)


col1, col2, col3 = st.columns([2, 1, 1])
with col1:
    compare_all = st.checkbox("Compare all 4 strategies side by side")
with col2:
    strategy = st.selectbox("Strategy", STRATEGIES, format_func=_label_strategy, disabled=compare_all)
with col3:
    k = st.slider("Top-k", min_value=1, max_value=10, value=settings.retrieval_top_k)

if settings.llm_provider == "azure" and not settings.mock_mode:
    st.caption("Live mode - every Ask below is a real, rate-limited Azure API call (repeat questions are cached).")

if st.button("Ask", type="primary", disabled=not question.strip()):
    for strat in list(STRATEGIES) if compare_all else [strategy]:
        st.markdown(f"### `{strat}`")
        try:
            with st.spinner(f"Retrieving + generating ({strat})..."):
                answer, citations, latency_ms, docs, route = _cached_answer(question, strat, k)
        except Exception as exc:
            st.error(f"{strat} failed: {exc}")
            continue

        m1, m2, m3, m4 = st.columns(4)
        m1.metric("Latency", f"{latency_ms:.0f} ms")
        m2.metric("Retrieved chunks", len(docs))
        m3.metric("Citations resolved", len(citations))
        # Which path answered has to be visible: an enumeration or a total
        # from the complete incident index is a different kind of claim from
        # one assembled out of k chunks, and a reviewer cannot tell by reading
        # the prose.
        m4.metric("Route", route)
        if route == "aggregate":
            st.caption(
                "Aggregate route - the model was given the full incident index "
                "(every incident matching the services named, with date, severity, "
                "detection gap, duration and cost) alongside the retrieved chunks."
            )

        st.write(_escape_markdown_math(answer))

        with st.expander(f"Citations ({len(citations)})"):
            if not citations:
                st.caption("No citation tags resolved from the answer text.")
            for c in citations:
                st.markdown(f"**[{c.incident_id} · {c.section}]**")
                st.caption(_escape_markdown_math(c.snippet))

        with st.expander(f"Retrieved chunks, in rank order ({len(docs)})"):
            for i, d in enumerate(docs, start=1):
                st.markdown(f"**{i}. {d.metadata['incident_id']} · {d.metadata['section']}**")
                st.text(d.page_content[:500])

        st.divider()
