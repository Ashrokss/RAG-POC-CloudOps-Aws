"""
run() is a thin Typer wrapper around load_golden_questions/run_eval/
write_reports - mirroring cli/query.py and cli/ingest.py - so the actual
scoring logic stays directly unit-testable without going through Typer's
CliRunner or touching argv.
"""

from __future__ import annotations

from pathlib import Path
from typing import Optional

import typer

from eval.golden_schema import load_golden_questions
from eval.report import build_markdown_report, write_reports
from eval.runner import run_eval

app = typer.Typer()

_GOLDEN_QA_PATH = Path("data/golden_qa/golden_qa.yaml")


# Typer collapses a Typer() app with exactly one @app.command into a
# subcommand-less CLI; this no-op callback keeps 'run' addressable as
# 'python -m cli.eval run' instead of bare 'python -m cli.eval'.
@app.callback()
def _callback() -> None:
    pass


@app.command()
def run(
    strategies: str = typer.Option(
        "semantic,keyword,hybrid,hybrid_rerank", help="Comma-separated retrieval strategies to compare."
    ),
    k: int = typer.Option(5, help="Number of chunks to retrieve per question."),
    judge: str = typer.Option("heuristic", help="Answer-quality judge: heuristic|llm."),
    limit: Optional[int] = typer.Option(None, help="Only evaluate the first N golden questions."),
    run_label: str = typer.Option("latest", help="Label used to name the report and JSONL output files."),
) -> None:
    golden_questions = load_golden_questions(_GOLDEN_QA_PATH)
    if limit is not None:
        golden_questions = golden_questions[:limit]

    strategy_list = [s.strip() for s in strategies.split(",")]
    records = run_eval(golden_questions, strategies=strategy_list, k=k, judge=judge, run_label=run_label)

    md_path, csv_path = write_reports(records, run_label)
    typer.echo(build_markdown_report(records))
    typer.echo(f"\nWrote {md_path} and {csv_path}")


if __name__ == "__main__":
    app()