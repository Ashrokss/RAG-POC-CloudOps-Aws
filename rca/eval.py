"""
A live accuracy spot-check for rca/, which - unlike rag/ - had no golden set
or scoring code of its own before this. Sized to what this pipeline actually
needs: route-match and must-mention recall, not rag/'s eval/ package's doc-id
recall/precision/mrr machinery, which assumes a ranked list of documents to
compare against a relevance set - a shape that does not map cleanly onto
rca/'s single-hop lookup and known_pattern short-circuit question shapes.

Cost note for anyone about to run this live: a known_pattern-route answer
makes zero chat-model calls (render_known_pattern_answer reads two
already-written okf/ files); only retrieval, aggregate, and gap-route
answers spend one live call each.

must_mention is a lowercase substring check against the answer text plus its
citations - loose on purpose. This is a spot-check for route and gross
factual correctness (does the right incident's name/number show up at all),
not a golden-set-grade grounding audit; eval/grounding.py's sentence-scoped
date/number checking is the tool for that and lives on rag/'s side.
"""

from __future__ import annotations

import json
from pathlib import Path

import yaml
from pydantic import BaseModel, ValidationError

from rca.answer import ask
from rca.models import Route
from rca.providers import ChatModel
from rca.retrieve import Retriever
from rca.store import Store

QUESTIONS_PATH = Path(__file__).resolve().parents[1] / "data" / "rca_qa" / "spotcheck.yaml"
_REPORTS_DIR = Path("reports")


class SpotCheckQuestion(BaseModel):
    id: str
    question: str
    expected_route: Route
    must_mention: list[str] = []
    notes: str = ""


def load_questions(path: Path = QUESTIONS_PATH) -> list[SpotCheckQuestion]:
    """Fails on the first bad row, same as rag/'s eval/golden_schema.py: this
    set is small and hand-authored, so a malformed entry is a typo worth
    fixing immediately, not one of many worth batching into a report."""
    raw_entries = yaml.safe_load(path.read_text(encoding="utf-8")) or []
    questions: list[SpotCheckQuestion] = []
    for index, entry in enumerate(raw_entries):
        try:
            questions.append(SpotCheckQuestion(**entry))
        except ValidationError as exc:
            question_text = entry.get("question", "<missing>") if isinstance(entry, dict) else repr(entry)
            raise ValueError(f"Spot-check question at index {index} ({question_text!r}) failed validation:\n{exc}") from exc
    return questions


def _score_one(store: Store, retriever: Retriever, chat: ChatModel, question: SpotCheckQuestion) -> dict:
    answer = ask(store, retriever, chat, question.question, k=5)
    haystack = f"{answer.answer}\n{' '.join(answer.citations)}".lower()
    mentioned = [needle for needle in question.must_mention if needle.lower() in haystack]

    return {
        "id": question.id,
        "question": question.question,
        "expected_route": question.expected_route,
        "route": answer.route,
        "route_match": answer.route == question.expected_route,
        "must_mention": question.must_mention,
        "mentioned": mentioned,
        "must_mention_recall": (len(mentioned) / len(question.must_mention)) if question.must_mention else None,
        "answer": answer.answer,
        "citations": answer.citations,
        "coverage": answer.coverage,
        "latency_ms": answer.latency_ms,
        "model_id": answer.model_id,
        "notes": question.notes,
    }


def run_eval(
    store: Store, retriever: Retriever, chat: ChatModel, questions: list[SpotCheckQuestion]
) -> list[dict]:
    return [_score_one(store, retriever, chat, question) for question in questions]


def build_markdown_report(records: list[dict]) -> str:
    lines = [
        "| ID | Expected route | Actual route | Route match | Must-mention recall | Latency |",
        "|---|---|---|---|---|---|",
    ]
    for r in records:
        recall = "-" if r["must_mention_recall"] is None else f"{r['must_mention_recall']:.2f}"
        lines.append(
            f"| {r['id']} | {r['expected_route']} | {r['route']} | "
            f"{'yes' if r['route_match'] else 'no'} | {recall} | {r['latency_ms']:.0f}ms |"
        )

    route_matches = sum(1 for r in records if r["route_match"])
    full_recall = sum(1 for r in records if r["must_mention_recall"] in (None, 1.0))
    lines += [
        "",
        f"Route matched expectation: {route_matches}/{len(records)}",
        f"Full must-mention recall (or no requirement): {full_recall}/{len(records)}",
    ]
    return "\n".join(lines)


def write_reports(records: list[dict], run_label: str) -> tuple[Path, Path]:
    _REPORTS_DIR.mkdir(parents=True, exist_ok=True)
    md_path = _REPORTS_DIR / f"rca_spotcheck_{run_label}.md"
    json_path = _REPORTS_DIR / f"rca_spotcheck_{run_label}.json"
    md_path.write_text(build_markdown_report(records), encoding="utf-8")
    json_path.write_text(json.dumps(records, indent=2), encoding="utf-8")
    return md_path, json_path
