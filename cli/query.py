"""
compare exists to make retrieval-strategy differences visible interactively
- it calls the exact same answer_question() the eval runner scores against,
just once per strategy with its result printed immediately instead of
aggregated into a report, so a strategy regression can be eyeballed without
running the full eval harness.
"""

from __future__ import annotations

import typer

from rag.chain.rag_chain import answer_question

app = typer.Typer()


@app.command()
def ask(
    question: str,
    strategy: str = typer.Option("hybrid", help="Retrieval strategy: semantic|keyword|hybrid|hybrid_rerank."),
    k: int = typer.Option(5, help="Number of chunks to retrieve."),
) -> None:
    result = answer_question(question, strategy=strategy, k=k)

    typer.echo(result.answer)
    typer.echo("")
    typer.echo(f"Citations ({len(result.citations)}):")
    for citation in result.citations:
        typer.echo(f"  [{citation.incident_id} · {citation.section}] {citation.snippet}")


@app.command()
def compare(
    question: str,
    strategies: str = typer.Option("semantic,keyword,hybrid", help="Comma-separated retrieval strategies."),
) -> None:
    for strategy in [s.strip() for s in strategies.split(",")]:
        result = answer_question(question, strategy=strategy)

        typer.echo(f"=== {strategy} ===")
        typer.echo(f"Retrieved doc ids: {result.retrieved_doc_ids}")
        typer.echo(result.answer)
        typer.echo("")


if __name__ == "__main__":
    app()
