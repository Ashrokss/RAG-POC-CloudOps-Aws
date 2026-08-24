"""
One entry point for the whole loop: ingest, ask, see the gaps, research them,
review what came back, promote what a human approves, write an RCA.

`review approve` takes --actor and records it. There is no unattributed path
into the knowledge base.
"""

from __future__ import annotations

from pathlib import Path
from typing import Optional

import typer

from rca import eval as eval_mod
from rca import research as research_mod
from rca import review as review_mod
from rca.answer import ask as ask_pipeline
from rca.ingest import ingest_dirs
from rca.providers import get_chat_model, get_embedder
from rca.report import generate_rca, render_markdown
from rca.retrieve import Retriever
from rca.store import Store
from rca.verify import verify as verify_card

app = typer.Typer(help="RCA knowledge platform")
gaps_app = typer.Typer(help="Knowledge gaps opened by unanswerable questions")
review_app = typer.Typer(help="Human review queue - the only path into the knowledge base")
app.add_typer(gaps_app, name="gaps")
app.add_typer(review_app, name="review")

DB = "data/rca.db"
CORPUS = [Path("data/raw_rca_docs/real"), Path("data/raw_rca_docs/synthetic")]


def _wired() -> tuple[Store, Retriever, object]:
    store = Store(DB)
    return store, Retriever(store, get_embedder()), get_chat_model()


@app.command()
def ingest(
    reset: bool = typer.Option(False, "--reset", help="Drop the database first."),
    plane: str = typer.Option("evidence", help="evidence|concept"),
) -> None:
    if reset and Path(DB).exists():
        Path(DB).unlink()
    store = Store(DB)
    stats = ingest_dirs(store, CORPUS, plane=plane)
    cards = Path("knowledge/cards")
    if cards.exists() and any(cards.glob("*.md")):
        promoted = ingest_dirs(store, [cards], plane="concept", tier="reference")
        stats["concept_docs"] = promoted["docs"]
    typer.echo(f"{stats} | embedding models in store: {sorted(store.embedding_models())}")


@app.command()
def ask(question: str, k: int = typer.Option(5)) -> None:
    store, retriever, chat = _wired()
    answer = ask_pipeline(store, retriever, chat, question, k)
    typer.echo(f"[route={answer.route} coverage={answer.coverage:.2f} {answer.latency_ms:.0f}ms]\n")
    typer.echo(answer.answer)
    if answer.citations:
        typer.echo("\nCitations: " + ", ".join(answer.citations))
    if answer.gap_id:
        typer.echo(
            f"\nKnowledge gap opened: {answer.gap_id}\n"
            f"  research it:  python -m rca.cli gaps research {answer.gap_id}"
        )


@app.command("eval")
def eval_cmd(
    k: int = typer.Option(5),
    run_label: str = typer.Option("latest", "--run-label", help="Names reports/rca_spotcheck_<label>.md/.json"),
) -> None:
    """Live spot-check against data/rca_qa/spotcheck.yaml - see rca/eval.py
    for what this does and does not cover."""
    store, retriever, chat = _wired()
    questions = eval_mod.load_questions()
    records = eval_mod.run_eval(store, retriever, chat, questions)
    md_path, json_path = eval_mod.write_reports(records, run_label)
    typer.echo(eval_mod.build_markdown_report(records))
    typer.echo(f"\nWrote {md_path} and {json_path}")


@gaps_app.command("list")
def gaps_list(status: Optional[str] = typer.Option(None)) -> None:
    store = Store(DB)
    for gap in store.gaps(status):
        typer.echo(f"{gap.gap_id}  {gap.status:11s} x{gap.hit_count:<3d} {gap.reason:14s} {gap.question[:70]}")


@gaps_app.command("research")
def gaps_research(gap_id: str) -> None:
    """Offline by default: with no search backend configured this reports that
    it found nothing rather than inventing an answer."""
    store, retriever, chat = _wired()
    gap = store.get_gap(gap_id)
    if gap is None:
        raise typer.BadParameter(f"no gap {gap_id!r}")

    card = research_mod.research(store, gap)
    if card is None:
        typer.echo("No sources found (offline search backend). Gap stays open.")
        raise typer.Exit(code=0)

    verdict = verify_card(store, card, chat)
    typer.echo(f"candidate {card.candidate_id} -> {card.status} (confidence {card.confidence})")
    for note in verdict.notes:
        typer.echo(f"  ! {note}")


@review_app.command("list")
def review_list() -> None:
    store = Store(DB)
    for card in review_mod.queue(store):
        verdict = card.verdict
        typer.echo(f"{card.candidate_id}  {card.status:12s} conf={card.confidence:.2f}  {card.claim[:60]}")
        if verdict:
            typer.echo(
                f"    quotes {verdict.quotes_verified}/{verdict.quotes_total} "
                f"authority {verdict.authority_score} votes {verdict.votes_for}/{verdict.votes_total}"
            )
            for note in verdict.notes:
                typer.echo(f"    ! {note}")


@review_app.command("approve")
def review_approve(candidate_id: str, actor: str = typer.Option(..., help="Who is approving.")) -> None:
    store, retriever, _ = _wired()
    path = review_mod.approve(store, candidate_id, actor, retriever=retriever)
    typer.echo(f"promoted -> {path}\nCommit it: knowledge/ is the concept plane and lives in git.")


@review_app.command("reject")
def review_reject(
    candidate_id: str,
    actor: str = typer.Option(...),
    reason: str = typer.Option(..., help="Required - the only record of why."),
) -> None:
    store = Store(DB)
    review_mod.reject(store, candidate_id, actor, reason)
    typer.echo(f"rejected {candidate_id}; gap reopened")


@app.command()
def rca(incident_id: str, out: Optional[Path] = typer.Option(None)) -> None:
    store, retriever, chat = _wired()
    report = generate_rca(store, retriever, chat, incident_id)
    markdown = render_markdown(report)
    if out:
        out.write_text(markdown, encoding="utf-8")
        typer.echo(f"wrote {out}")
    else:
        typer.echo(markdown)


@app.command()
def audit(subject: Optional[str] = typer.Option(None)) -> None:
    store = Store(DB)
    for row in store.audit_trail(subject):
        typer.echo(f"{row['ts']}  {row['actor']:10s} {row['action']:22s} {row['subject_id']}  {row['detail'][:60]}")


if __name__ == "__main__":
    app()
