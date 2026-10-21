"""Originality check against the jobs this machine already produced.

Similarity is computed locally over word trigrams: cheap, deterministic, and
honest about what it measures (lexical overlap, not ideas). The gate exists so
the factory cannot quietly ship the same video twice; it is enforced when the
comparison is against real production history.
"""
from __future__ import annotations

from dataclasses import dataclass

from .verification import normalize

DEFAULT_THRESHOLD = 0.55


@dataclass(frozen=True)
class PriorScript:
    job_id: str
    title: str
    text: str


@dataclass(frozen=True)
class OriginalityReport:
    verdict: str
    max_similarity: float
    nearest_job_id: str | None
    nearest_title: str | None
    compared: int
    threshold: float
    enforced: bool
    note: str = ""

    @property
    def too_similar(self) -> bool:
        return self.verdict == "too_similar"


def trigrams(text: str) -> set[str]:
    """Word trigrams; short texts fall back to bigrams so overlap is still measurable."""
    tokens = [token for token in normalize(text).split() if token]
    if not tokens:
        return set()
    if len(tokens) < 3:
        return {" ".join(tokens)} if len(tokens) == 1 else {
            " ".join(tokens[index:index + 2]) for index in range(len(tokens) - 1)
        }
    return {" ".join(tokens[index:index + 3]) for index in range(len(tokens) - 2)}


def similarity(left: str, right: str) -> float:
    """Jaccard overlap of trigram sets, rounded to four decimals."""
    a, b = trigrams(left), trigrams(right)
    if not a or not b:
        return 0.0
    return round(len(a & b) / len(a | b), 4)


def check_originality(
    text: str,
    prior: list[PriorScript],
    *,
    threshold: float = DEFAULT_THRESHOLD,
    enforced: bool = True,
) -> OriginalityReport:
    """Compare one script against earlier jobs and report the nearest neighbour."""
    best: tuple[float, PriorScript] | None = None
    for candidate in prior:
        score = similarity(text, candidate.text)
        if best is None or score > best[0]:
            best = (score, candidate)
    if best is None:
        return OriginalityReport(
            verdict="original", max_similarity=0.0, nearest_job_id=None, nearest_title=None,
            compared=0, threshold=threshold, enforced=enforced,
            note="no earlier script to compare against",
        )
    score, nearest = best
    too_close = score >= threshold
    return OriginalityReport(
        verdict="too_similar" if too_close else "original",
        max_similarity=score,
        nearest_job_id=nearest.job_id,
        nearest_title=nearest.title,
        compared=len(prior),
        threshold=threshold,
        enforced=enforced,
        note=(
            f"highest overlap {score:.2f} with {nearest.job_id[:8]}"
            if too_close else f"highest overlap {score:.2f} stays under {threshold:.2f}"
        ),
    )


def prior_scripts_from(store, *, exclude_job_id: str, limit: int = 50) -> list[PriorScript]:
    """Read earlier jobs' scripts from the store, skipping anything unreadable."""
    prior: list[PriorScript] = []
    for record in store.list(limit=limit):
        if record.id == exclude_job_id:
            continue
        try:
            data = store.read_artifact(record.id, "script.json")
        except (OSError, ValueError, KeyError):
            continue
        text = " ".join(segment.get("text", "") for segment in data.get("segments", []))
        prior.append(PriorScript(job_id=record.id, title=data.get("title", record.title), text=text))
    return prior
