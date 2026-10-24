"""What this machine already produced, handed to the next research stage.

The runner used to pass empty lists into research and topic selection, so every
job re-proposed the same angles and the only novelty guard was the post-hoc
`originality.json` check. This module reads the real production history once per
stage: titles become the research avoid-list, genres become the recent-genre
context for topic selection.

Reading is deliberately forgiving. A job whose artifacts were deleted, are
half-written or fail their schema is skipped, not fatal: losing one row of
context must never stop a run.
"""
from __future__ import annotations

from dataclasses import dataclass, field


@dataclass(frozen=True)
class ProductionHistory:
    titles: list[str] = field(default_factory=list)
    genres: list[str] = field(default_factory=list)


def _genre_from(data: dict) -> str:
    value = data.get("genre")
    if isinstance(value, str) and value:
        return value
    return ""


def production_history(store, *, exclude_job_id: str, limit: int = 60) -> ProductionHistory:
    """Read what this machine already produced; unreadable jobs are skipped, not fatal."""
    titles: list[str] = []
    genres: list[str] = []
    for record in store.list(limit=limit):
        if record.id == exclude_job_id:
            continue
        title = (record.title or "").strip()
        if title:
            titles.append(title)
        try:
            script = store.read_artifact(record.id, "script.json")
        except (OSError, ValueError, KeyError):
            script = {}
        genre = _genre_from(script)
        if not genre:
            try:
                topic = store.read_artifact(record.id, "topic.json")
            except (OSError, ValueError, KeyError):
                topic = {}
            genre = _genre_from(topic.get("topic") or {})
        if genre:
            genres.append(genre)
    return ProductionHistory(
        titles=list(dict.fromkeys(titles)),
        genres=list(dict.fromkeys(genres)),
    )
