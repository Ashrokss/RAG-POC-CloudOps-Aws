"""
load_golden_questions fails on the first bad row rather than collecting every
error across the file: a golden set this small is hand-authored and reviewed
by a person before each eval run, so one malformed entry is far more likely
to be a typo worth fixing immediately than one of many rows worth batching
into a report.
"""

from __future__ import annotations

from pathlib import Path

import yaml
from pydantic import ValidationError

from rag.models import GoldenQuestion


def load_golden_questions(path: Path) -> list[GoldenQuestion]:
    raw_entries = yaml.safe_load(path.read_text(encoding="utf-8")) or []

    questions: list[GoldenQuestion] = []
    for index, entry in enumerate(raw_entries):
        try:
            questions.append(GoldenQuestion(**entry))
        except ValidationError as exc:
            question_text = entry.get("question", "<missing>") if isinstance(entry, dict) else repr(entry)
            raise ValueError(
                f"Golden question at index {index} ({question_text!r}) failed validation:\n{exc}"
            ) from exc

    return questions