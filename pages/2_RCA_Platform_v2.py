"""
Read-only console for the v2 platform.

Deliberately read-only: this App Service has no authentication, and the whole
design rests on "only a named human promotes knowledge". An anonymous Approve
button on a public URL would make that sentence false. Promotion stays on the
authenticated CLI path:

    python -m rca.cli review approve <id> --actor you@example.com

What this page is for is seeing the machinery work - what the system answers,
what it admits it cannot answer, and what is sitting in the queue waiting on a
person.
"""

from __future__ import annotations

import os
from pathlib import Path

import streamlit as st

from rca.answer import ask as ask_pipeline
from rca.providers import get_chat_model, get_embedder
from rca.report import generate_rca, render_markdown
from rca.retrieve import Retriever
from rca.store import Store

st.set_page_config(page_title="RCA Platform v2", page_icon="🧭", layout="wide")
st.title("RCA Platform v2 — gap-driven knowledge")

DB = os.getenv("RCA_DB", "data/rca.db")


def _escape(text: str) -> str:
    # st.write renders "$...$" as LaTeX; a dollar figure in an answer would
    # otherwise come out as mangled equation glyphs.
    return text.replace("$", "\\$")


@st.cache_resource(show_spinner=False)
def _wired():
    store = Store(DB)
    return store, Retriever(store, get_embedder()), get_chat_model()


if not Path(DB).exists():
    st.error(f"No store at `{DB}`. Run `python -m rca.cli ingest --reset` and redeploy.")
    st.stop()

store, retriever, chat = _wired()
counts = store.counts()

with st.sidebar:
    st.subheader("Store")
    st.write(f"Documents: **{counts['docs']}**")
    st.write(f"Chunks: **{counts['chunks']}**")
    st.write(f"Open gaps: **{len([g for g in store.gaps() if g.status == 'open'])}**")
    st.write(f"Candidates: **{counts['candidates']}**")
    st.write("Embedding model(s):", ", ".join(f"`{m}`" for m in sorted(store.embedding_models())) or "—")
    st.write(f"Chat model: `{chat.model_id}`")
    st.divider()
    st.caption(
        "Read-only. Promotion into the knowledge base happens on the CLI, with a "
        "named approver, because this app has no authentication."
    )

ask_tab, gaps_tab, queue_tab, rca_tab, audit_tab = st.tabs(
    ["Ask", "Knowledge gaps", "Review queue", "RCA report", "Audit"]
)

with ask_tab:
    question = st.text_area("Question", height=80, key="v2_question")
    k = st.slider("Top-k", 1, 10, 5)
    if st.button("Ask", type="primary", disabled=not question.strip()):
        with st.spinner("Routing, retrieving, generating..."):
            answer = ask_pipeline(store, retriever, chat, question, k)

        c1, c2, c3, c4 = st.columns(4)
        c1.metric("Route", answer.route)
        c2.metric("Coverage", f"{answer.coverage:.2f}")
        c3.metric("Citations", len(answer.citations))
        c4.metric("Latency", f"{answer.latency_ms:.0f} ms")

        if answer.route == "gap":
            # The interesting outcome, not the failure one.
            st.warning(
                f"**Knowledge gap opened** (`{answer.gap_id}`). The corpus cannot answer this. "
                "It is now queued for research rather than answered from guesswork."
            )
        elif answer.route == "known_pattern":
            st.info(
                "**Known-pattern route** — retrieval matched 2+ past incidents already "
                "catalogued under one `okf/failure-modes/` entry, so this answer is that "
                "failure mode's existing playbook, not a fresh analysis. No chat model call "
                "was made for this answer."
            )
        st.write(_escape(answer.answer))
        if answer.citations:
            st.caption("Citations: " + ", ".join(f"`{c}`" for c in answer.citations))

with gaps_tab:
    st.caption("Questions the corpus could not answer, most-asked first. Hit count is the priority signal.")
    rows = store.gaps()
    if not rows:
        st.info("No gaps recorded yet.")
    for gap in rows:
        st.markdown(
            f"**`{gap.gap_id}`** · {gap.status} · asked **{gap.hit_count}×** · "
            f"reason `{gap.reason}` · best score {gap.best_score:.2f}"
        )
        st.caption(gap.question)

with queue_tab:
    st.caption(
        "Candidates awaiting a human. AI-rejected cards stay visible on purpose — "
        "a verifier that silently bins things is a verifier nobody audits."
    )
    cards = store.candidates()
    if not cards:
        st.info("Nothing researched yet.")
    for card in cards:
        with st.expander(f"{card.status} · confidence {card.confidence:.2f} · {card.claim[:70]}"):
            st.write(_escape(card.claim))
            if card.verdict:
                v = card.verdict
                st.write(
                    f"Quotes verified **{v.quotes_verified}/{v.quotes_total}** · "
                    f"authority **{v.authority_score}** · votes **{v.votes_for}/{v.votes_total}**"
                )
                for note in v.notes:
                    st.warning(note)
            for item in card.evidence:
                st.markdown(f"- [{item.title or item.url}]({item.url}) — `{item.authority}`")
                st.caption(_escape(item.quote))
            st.code(
                f"python -m rca.cli review approve {card.candidate_id} --actor you@example.com",
                language="bash",
            )

with rca_tab:
    incidents = [row["incident_id"] for row in store.incidents() if row["incident_id"]]
    incident_id = st.selectbox("Incident", incidents) if incidents else None
    if incident_id and st.button("Generate RCA"):
        with st.spinner("Assembling section by section..."):
            report = generate_rca(store, retriever, chat, incident_id)
        if report.unsupported_fields:
            st.warning(
                "Not supported by the corpus, left empty rather than filled in: "
                + ", ".join(f"`{f}`" for f in report.unsupported_fields)
            )
        st.markdown(_escape(render_markdown(report)))

with audit_tab:
    st.caption("Every change to what the system believes, and who made it.")
    trail = store.audit_trail()[-200:]
    if not trail:
        st.info("No audit entries yet.")
    for row in reversed(trail):
        st.text(f"{row['ts'][:19]}  {row['actor']:<24} {row['action']:<22} {row['subject_id']}")
