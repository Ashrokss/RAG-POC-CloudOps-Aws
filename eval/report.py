"""
Markdown and CSV are both built from aggregate_metrics' grouped averages
rather than one being derived from the other's string output: a spreadsheet
import of the CSV needs bare numeric cells, not a "0.833" sitting inside a
pipe-delimited markdown table column, and a markdown reviewer needs the
Best-strategy-per-question-type section a CSV has no natural place to put.

One section per question set, never a pooled table: the adversarial set is
scored on refusal, required-id recall and grounding, the golden set on token
overlap, and a single averaged row over both would let 89 easy questions bury
13 hard ones. The adversarial section carries its own columns for exactly
that reason - a strategy that answers everything and refuses nothing shows up
as a 0.000 refusal column, not as a slightly lower quality score.
"""

from __future__ import annotations

import csv
import io
from pathlib import Path

from eval.retrieval_metrics import aggregate_metrics

_REPORTS_DIR = Path("reports")
_BASE_COLUMNS = ("recall", "precision", "mrr", "quality_score", "latency_ms")
_ADVERSARIAL_COLUMNS = (
    "refusal_correct",
    "required_id_recall",
    "forbidden_id_leak",
    "grounding_date_violations",
    "grounding_number_violations",
    "grounding_unretrieved_incidents",
)


def _columns_for(rows: list[tuple[tuple[str, str, str], dict]]) -> tuple[str, ...]:
    present = {field for _, metrics in rows for field in metrics}
    return _BASE_COLUMNS + tuple(col for col in _ADVERSARIAL_COLUMNS if col in present)


def _sorted_rows(aggregated: dict) -> list[tuple[tuple[str, str, str], dict]]:
    return sorted(aggregated.items(), key=lambda item: (item[0][0], item[0][2], item[0][1]))


def _format(value: float, column: str) -> str:
    if column == "latency_ms":
        return f"{value:.1f}"
    if column.startswith("grounding"):
        return f"{value:.2f}"
    return f"{value:.3f}"


def build_markdown_report(records: list[dict]) -> str:
    aggregated = aggregate_metrics(records)
    lines: list[str] = []

    for question_set in sorted({key[0] for key in aggregated}):
        rows = [(key, metrics) for key, metrics in _sorted_rows(aggregated) if key[0] == question_set]
        columns = _columns_for(rows)

        lines.append(f"## Question set: `{question_set}`")
        lines.append("")
        lines.append("| Strategy | Question Type | " + " | ".join(columns) + " | N |")
        lines.append("|---" * (len(columns) + 3) + "|")
        for (_, strategy, question_type), metrics in rows:
            cells = [_format(metrics.get(column, 0.0), column) for column in columns]
            lines.append(
                f"| {strategy} | {question_type} | " + " | ".join(cells) + f" | {int(metrics.get('n', 0))} |"
            )

        lines.append("")
        lines.append("### Best strategy per question type")
        lines.append("")
        for question_type in sorted({key[2] for key, _ in rows}):
            candidates = [
                (key[1], metrics) for key, metrics in rows if key[2] == question_type
            ]
            best_strategy, best_metrics = max(
                candidates, key=lambda item: item[1].get("quality_score", 0.0)
            )
            lines.append(
                f"- **{question_type}**: `{best_strategy}` "
                f"(quality_score={best_metrics.get('quality_score', 0.0):.3f})"
            )
        lines.append("")

    return "\n".join(lines).rstrip() + "\n"


def build_csv_report(records: list[dict]) -> str:
    aggregated = aggregate_metrics(records)
    rows = _sorted_rows(aggregated)
    columns = _columns_for(rows)

    buffer = io.StringIO()
    writer = csv.writer(buffer)
    writer.writerow(["question_set", "strategy", "question_type", *columns, "n"])
    for (question_set, strategy, question_type), metrics in rows:
        writer.writerow(
            [
                question_set,
                strategy,
                question_type,
                *(f"{metrics.get(column, 0.0):.4f}" for column in columns),
                int(metrics.get("n", 0)),
            ]
        )

    return buffer.getvalue()


def write_reports(records: list[dict], run_label: str) -> tuple[Path, Path]:
    _REPORTS_DIR.mkdir(parents=True, exist_ok=True)
    md_path = _REPORTS_DIR / f"eval_comparison_{run_label}.md"
    csv_path = _REPORTS_DIR / f"eval_comparison_{run_label}.csv"

    md_path.write_text(build_markdown_report(records), encoding="utf-8")
    csv_path.write_text(build_csv_report(records), encoding="utf-8")

    return md_path, csv_path
