"""Pipeline state machine with an explicit transition allow-list."""

from __future__ import annotations

from enum import Enum


class JobState(str, Enum):
    IDEA_DISCOVERY = "IDEA_DISCOVERY"
    TOPIC_SELECTED = "TOPIC_SELECTED"
    SCRIPT_GENERATED = "SCRIPT_GENERATED"
    CREATIVE_REVIEW = "CREATIVE_REVIEW"
    STORYBOARD_READY = "STORYBOARD_READY"
    ASSETS_READY = "ASSETS_READY"
    AUDIO_READY = "AUDIO_READY"
    RENDERING = "RENDERING"
    TECHNICAL_QC = "TECHNICAL_QC"
    EDITORIAL_QC = "EDITORIAL_QC"
    READY_FOR_APPROVAL = "READY_FOR_APPROVAL"
    APPROVED = "APPROVED"
    PRIVATE_UPLOAD = "PRIVATE_UPLOAD"
    SCHEDULED = "SCHEDULED"
    PUBLISHED = "PUBLISHED"
    FAILED = "FAILED"
    CANCELLED = "CANCELLED"
    REJECTED = "REJECTED"
    BLOCKED = "BLOCKED"


TRANSITIONS: dict[JobState, set[JobState]] = {
    JobState.IDEA_DISCOVERY: {JobState.TOPIC_SELECTED, JobState.FAILED, JobState.CANCELLED, JobState.BLOCKED},
    JobState.TOPIC_SELECTED: {JobState.SCRIPT_GENERATED, JobState.FAILED, JobState.CANCELLED, JobState.BLOCKED},
    JobState.SCRIPT_GENERATED: {JobState.CREATIVE_REVIEW, JobState.FAILED, JobState.CANCELLED, JobState.BLOCKED},
    JobState.CREATIVE_REVIEW: {
        JobState.STORYBOARD_READY,
        JobState.SCRIPT_GENERATED,  # revision loop
        JobState.REJECTED,
        JobState.FAILED,
        JobState.CANCELLED,
        JobState.BLOCKED,
    },
    JobState.STORYBOARD_READY: {JobState.ASSETS_READY, JobState.FAILED, JobState.CANCELLED, JobState.BLOCKED},
    JobState.ASSETS_READY: {JobState.AUDIO_READY, JobState.FAILED, JobState.CANCELLED, JobState.BLOCKED},
    JobState.AUDIO_READY: {JobState.RENDERING, JobState.FAILED, JobState.CANCELLED, JobState.BLOCKED},
    JobState.RENDERING: {JobState.TECHNICAL_QC, JobState.FAILED, JobState.CANCELLED, JobState.BLOCKED},
    JobState.TECHNICAL_QC: {JobState.EDITORIAL_QC, JobState.RENDERING, JobState.FAILED, JobState.CANCELLED, JobState.BLOCKED},
    JobState.EDITORIAL_QC: {JobState.READY_FOR_APPROVAL, JobState.REJECTED, JobState.FAILED, JobState.CANCELLED, JobState.BLOCKED},
    JobState.READY_FOR_APPROVAL: {JobState.APPROVED, JobState.REJECTED, JobState.CANCELLED},
    JobState.APPROVED: {JobState.PRIVATE_UPLOAD, JobState.CANCELLED},
    JobState.PRIVATE_UPLOAD: {JobState.SCHEDULED, JobState.FAILED, JobState.CANCELLED, JobState.BLOCKED},
    JobState.SCHEDULED: {JobState.PUBLISHED, JobState.CANCELLED, JobState.FAILED},
    JobState.PUBLISHED: set(),
    JobState.FAILED: {JobState.IDEA_DISCOVERY},  # retry from earliest incomplete stage
    JobState.CANCELLED: set(),
    JobState.REJECTED: {JobState.IDEA_DISCOVERY},
    JobState.BLOCKED: {JobState.IDEA_DISCOVERY, JobState.CANCELLED},
}

# Ordered resume chain used to find the earliest incomplete stage.
PIPELINE_ORDER: list[JobState] = [
    JobState.IDEA_DISCOVERY,
    JobState.TOPIC_SELECTED,
    JobState.SCRIPT_GENERATED,
    JobState.CREATIVE_REVIEW,
    JobState.STORYBOARD_READY,
    JobState.ASSETS_READY,
    JobState.AUDIO_READY,
    JobState.RENDERING,
    JobState.TECHNICAL_QC,
    JobState.EDITORIAL_QC,
    JobState.READY_FOR_APPROVAL,
    JobState.APPROVED,
    JobState.PRIVATE_UPLOAD,
    JobState.SCHEDULED,
    JobState.PUBLISHED,
]

ARTIFACT_FOR_STATE: dict[JobState, str] = {
    JobState.TOPIC_SELECTED: "topic.json",
    JobState.SCRIPT_GENERATED: "script.json",
    JobState.CREATIVE_REVIEW: "review.json",
    JobState.STORYBOARD_READY: "storyboard.json",
    JobState.ASSETS_READY: "assets.json",
    JobState.AUDIO_READY: "audio.json",
    JobState.RENDERING: "render.json",
    JobState.TECHNICAL_QC: "qc.json",
    JobState.EDITORIAL_QC: "qc.json",
}


class IllegalTransition(ValueError):
    pass


def can_transition(src: JobState, dst: JobState) -> bool:
    return dst in TRANSITIONS.get(src, set())


def assert_transition(src: JobState, dst: JobState) -> None:
    if not can_transition(src, dst):
        allowed = sorted(s.value for s in TRANSITIONS.get(src, set()))
        raise IllegalTransition(f"{src.value} -> {dst.value} not allowed; allowed: {allowed}")


#: Titik henti pipeline untuk CLI dan API — satu sumber kebenaran.
STOP_POINTS: dict[str, JobState] = {
    "research": JobState.TOPIC_SELECTED,
    "script": JobState.SCRIPT_GENERATED,
    "creative": JobState.CREATIVE_REVIEW,
    "storyboard": JobState.STORYBOARD_READY,
    "audio": JobState.AUDIO_READY,
    "render": JobState.TECHNICAL_QC,
}
