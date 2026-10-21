from packages.core.orchestration.states import (
    PIPELINE_ORDER,
    STOP_POINTS,
    TRANSITIONS,
    IllegalTransition,
    JobState,
    assert_transition,
    can_transition,
)


def test_happy_path_is_connected():
    for a, b in zip(PIPELINE_ORDER, PIPELINE_ORDER[1:]):
        assert can_transition(a, b), f"{a} -> {b} must be legal"


def test_illegal_jump_rejected():
    assert not can_transition(JobState.IDEA_DISCOVERY, JobState.PUBLISHED)
    try:
        assert_transition(JobState.IDEA_DISCOVERY, JobState.PUBLISHED)
        raise AssertionError("expected IllegalTransition")
    except IllegalTransition as exc:
        assert "IDEA_DISCOVERY" in str(exc)


def test_terminal_states():
    assert TRANSITIONS[JobState.PUBLISHED] == set()
    assert TRANSITIONS[JobState.CANCELLED] == set()


def test_failure_can_restart():
    assert JobState.IDEA_DISCOVERY in TRANSITIONS[JobState.FAILED]
    assert JobState.BLOCKED in TRANSITIONS[JobState.IDEA_DISCOVERY]


def test_stop_points_cover_pipeline():
    assert STOP_POINTS["storyboard"] is JobState.STORYBOARD_READY
    assert STOP_POINTS["render"] is JobState.TECHNICAL_QC
    assert set(STOP_POINTS) == {"research", "script", "creative", "storyboard", "audio", "render"}
