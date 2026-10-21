"""Logical application agents. Each agent = prompt + provider routing + schema validation.

Agents do not spawn LLM processes by themselves; they ask the router, which owns
provider selection, health, retries and budget.
"""

from __future__ import annotations

import json

from .. import prompts
from ..jsonutil import extract_model
from ..providers.router import ProviderRouter
from ..storyboard_normalize import normalize_storyboard
from ..research.verification import Claim
from ..schemas import (
    CreativeReview,
    Genre,
    ResearchResult,
    Script,
    ScriptClaimList,
    Storyboard,
    TopicCandidate,
    TopicSelection,
    VideoMetadata,
    VerificationStatus,
)


class _AgentBase:
    tier = "worker"

    def __init__(self, router: ProviderRouter, *, name: str) -> None:
        self.router = router
        self.name = name

    def _ask(self, *, task: str, system: str, user: str, tier: str | None = None):
        return self.router.call(
            agent=self.name,
            tier=tier or self.tier,
            task=task,
            system=system,
            user=user,
        )


class ResearchAgent(_AgentBase):
    def __init__(self, router: ProviderRouter) -> None:
        super().__init__(router, name="ResearchAgent")

    def run(self, *, genres: list[Genre], avoid_titles: list[str], day_focus: str) -> ResearchResult:
        result = self._ask(
            task="research",
            system=prompts.RESEARCH_SYSTEM,
            user=prompts.research_user(genres=genres, avoid_titles=avoid_titles, day_focus=day_focus),
        )
        return extract_model(result.content, ResearchResult)


class TopicSelectionAgent(_AgentBase):
    def __init__(self, router: ProviderRouter) -> None:
        super().__init__(router, name="TopicSelectionAgent")

    def run(self, candidates: list[TopicCandidate], recent_genres: list[str]) -> TopicSelection:
        payload = json.dumps([c.model_dump(mode="json") for c in candidates], ensure_ascii=False)
        result = self._ask(
            task="topic_selection",
            system=prompts.TOPIC_SYSTEM,
            user=prompts.topic_user(payload, recent_genres),
        )
        selection = extract_model(result.content, TopicSelection)
        if not any(c.topic_id == selection.selected_topic_id for c in candidates):
            raise ValueError(
                f"selection referenced unknown topic {selection.selected_topic_id!r}; "
                f"available: {[c.topic_id for c in candidates]}"
            )
        return selection

    def resolve(self, candidates: list[TopicCandidate], selection: TopicSelection) -> TopicCandidate:
        for c in candidates:
            if c.topic_id == selection.selected_topic_id:
                return c
        raise ValueError(f"topic {selection.selected_topic_id!r} not found")


class ScriptAgent(_AgentBase):
    def __init__(self, router: ProviderRouter) -> None:
        super().__init__(router, name="ScriptAgent")

    def run(self, topic: TopicCandidate) -> Script:
        result = self._ask(
            task="script",
            system=prompts.SCRIPT_SYSTEM,
            user=prompts.script_user(topic.model_dump_json()),
        )
        script = extract_model(result.content, Script)
        if script.content_type == "fictional":
            script.sources = []
            script.verification_status = VerificationStatus.fictional
        else:
            script.verification_status = VerificationStatus.needs_review
        if script.content_type == "factual" and not script.sources:
            script.sources = list(topic.sources)
        if script.content_type == "factual" and not script.sources:
            raise ValueError("factual script produced without any source reference")
        return script


class ClaimExtractorAgent(_AgentBase):
    """Pull the factual claims out of a finished script so its evidence can be checked."""

    def __init__(self, router: ProviderRouter) -> None:
        super().__init__(router, name="ClaimExtractorAgent")

    def run(self, script: Script) -> list[Claim]:
        result = self._ask(
            task="claim_extraction",
            system=prompts.CLAIM_SYSTEM,
            user=prompts.claim_user(script.model_dump_json()),
        )
        claims = extract_model(result.content, ScriptClaimList).claims
        return [Claim(statement=c.statement, quote=c.quote, source_url=c.source_url) for c in claims]


class CreativeDirectorAgent(_AgentBase):
    tier = "strategist"

    def __init__(self, router: ProviderRouter) -> None:
        super().__init__(router, name="CreativeDirectorAgent")

    def run(self, script: Script) -> CreativeReview:
        result = self._ask(
            task="creative_review",
            system=prompts.CREATIVE_SYSTEM,
            user=prompts.creative_user(script.model_dump_json()),
        )
        return extract_model(result.content, CreativeReview)

    @staticmethod
    def apply(script: Script, review: CreativeReview) -> Script:
        """Apply approved revisions in place, keeping segment order."""
        if review.verdict == "reject" or not review.revisions:
            return script
        segments = list(script.segments)
        for rev in review.revisions:
            idx = rev.get("segment_index")
            replacement = rev.get("replacement")
            if isinstance(idx, int) and 0 <= idx < len(segments) and isinstance(replacement, str) and replacement:
                segments[idx] = segments[idx].model_copy(update={"text": replacement})
        return script.model_copy(update={"segments": segments})


class StoryboardAgent(_AgentBase):
    def __init__(self, router: ProviderRouter, *, fps: int, width: int, height: int) -> None:
        super().__init__(router, name="StoryboardAgent")
        self.fps = fps
        self.width = width
        self.height = height

    last_raw: str = ""

    def run(self, script: Script) -> Storyboard:
        result = self._ask(
            task="storyboard",
            system=prompts.STORYBOARD_SYSTEM,
            user=prompts.storyboard_user(
                script.model_dump_json(), fps=self.fps, width=self.width, height=self.height
            ),
        )
        self.last_raw = result.content
        raw = extract_model(result.content, dict, wrap_key="scenes")
        normalized = normalize_storyboard(
            raw,
            fallback_id=script.title.lower().replace(" ", "-")[:48],
            fps=self.fps,
            width=self.width,
            height=self.height,
            language="id-ID",
        )
        if len(normalized["scenes"]) != len(script.segments):
            raise ValueError("storyboard must return one scene per script segment")
        for scene, segment in zip(normalized["scenes"], script.segments):
            scene["segment"] = segment.text
        normalized.update(fps=self.fps, width=self.width, height=self.height, language="id-ID")
        storyboard = Storyboard.model_validate(normalized)
        return _renumber(storyboard)


def _renumber(storyboard: Storyboard) -> Storyboard:
    """Deterministic re-timing: no gaps, no overlaps, renderer-safe ordering."""
    scenes = sorted(storyboard.scenes, key=lambda s: s.startFrame)
    cursor = 0
    fixed = []
    for scene in scenes:
        updated = scene.model_copy(update={"startFrame": cursor})
        fixed.append(updated)
        cursor += updated.durationInFrames
    return storyboard.model_copy(update={"scenes": fixed})


class QualityAgent(_AgentBase):
    def __init__(self, router: ProviderRouter) -> None:
        super().__init__(router, name="QualityAgent")

    def run(self, storyboard: Storyboard, script: Script) -> dict:
        result = self._ask(
            task="quality",
            system=prompts.QUALITY_SYSTEM,
            user=prompts.quality_user(storyboard, script.model_dump_json()),
        )
        from ..artifacts import DraftQualityArtifact
        return extract_model(result.content, DraftQualityArtifact).model_dump(mode="json", by_alias=True)


class MetadataAgent(_AgentBase):
    def __init__(self, router: ProviderRouter) -> None:
        super().__init__(router, name="MetadataAgent")

    def run(self, script: Script) -> VideoMetadata:
        result = self._ask(
            task="metadata",
            system=prompts.METADATA_SYSTEM,
            user=prompts.metadata_user(script.model_dump_json()),
        )
        return extract_model(result.content, VideoMetadata)
