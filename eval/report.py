"""
Markdown and CSV are both built from aggregate_metrics' grouped averages
rather than one being derived from the other's string output: a spreadsheet
import of the CSV needs bare numeric cells, not a "0.833" sitting inside a
pipe-delimited markdown table column, and a markdown reviewer needs the
Best-strategy-per-question-type section a CSV has no natural place to put.
"""

from __future__ import annotations

import csv
import io
from pathlib import Path

from eval.retrieval_metrics import aggregate_metrics

_REPORTS_DIR = Path("reports")
_COLUMNS = ("recall", "precision", "mrr", "quality_score", "latency_ms")


def build_markdown_report(records: list[dict]) -> str:
    aggregated = aggregate_metrics(records)
    rows = sorted(aggregated.items(), key=lambda item: (item[0][1], item[0][0]))

    lines = [
        "| Strategy | Question Type | Recall | Precision | MRR | Quality | Latency (ms) | N |",
        "|---|---|---|---|---|---|---|---|",
    ]
    for (strategy, question_type), metrics in rows:
        lines.append(
            f"| {strategy} | {question_type} | {metrics.get('recall', 0.0):.3f} | "
            f"{metrics.get('precision', 0.0):.3f} | {metrics.get('mrr', 0.0):.3f} | "
            f"{metrics.get('quality_score', 0.0):.3f} | {metrics.get('latency_ms', 0.0):.1f} | "
            f"{int(metrics.get('n', 0))} |"
        )

    lines.append("")
    lines.append("## Best strategy per question type")
    lines.append("")

    question_types = sorted({question_type for _, question_type in aggregated})
    for question_type in question_types:
        candidates = [
            (strategy, metrics) for (strategy, qt), metrics in aggregated.items() if qt == question_type
        ]
        best_strategy, best_metrics = max(candidates, key=lambda item: item[1].get("quality_score", 0.0))
        lines.append(
            f"- **{question_type}**: `{best_strategy}` "
            f"(quality_score={best_metrics.get('quality_score', 0.0):.3f})"
        )

    return "\n".join(lines)


def build_csv_report(records: list[dict]) -> str:
    aggregated = aggregate_metrics(records)
    rows = sorted(aggregated.items(), key=lambda item: (item[0][1], item[0][0]))

    buffer = io.StringIO()
    writer = csv.writer(buffer)
    writer.writerow(["strategy", "question_type", *_COLUMNS, "n"])
    for (strategy, question_type), metrics in rows:
        writer.writerow(
            [strategy, question_type, *(f"{metrics.get(col, 0.0):.4f}" for col in _COLUMNS), int(metrics.get("n", 0))]
        )

    return buffer.getvalue()


def write_reports(records: list[dict], run_label: str) -> tuple[Path, Path]:
    _REPORTS_DIR.mkdir(parents=True, exist_ok=True)
    md_path = _REPORTS_DIR / f"eval_comparison_{run_label}.md"
    csv_path = _REPORTS_DIR / f"eval_comparison_{run_label}.csv"

    md_path.write_text(build_markdown_report(records), encoding="utf-8")
    csv_path.write_text(build_csv_report(records), encoding="utf-8")

    return md_path, csv_path