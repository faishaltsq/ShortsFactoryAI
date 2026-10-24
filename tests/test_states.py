from packages.core.orchestration.states import (
    PIPELINE_ORDER,
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


def test_content_revision_can_rewind_from_storyboard():
    """A storyboard that fails the draft gate may re-script; the loop then restarts."""
    assert can_transition(JobState.STORYBOARD_READY, JobState.SCRIPT_GENERATED)


def test_attempt_cap_can_block_a_failed_job():
    assert can_transition(JobState.FAILED, JobState.BLOCKED)
    assert can_transition(JobState.FAILED, JobState.IDEA_DISCOVERY)


def test_blocked_job_can_be_resumed_or_cancelled_but_not_approved():
    assert can_transition(JobState.BLOCKED, JobState.IDEA_DISCOVERY)
    assert can_transition(JobState.BLOCKED, JobState.CANCELLED)
    assert not can_transition(JobState.BLOCKED, JobState.APPROVED)


def test_approved_job_can_be_re_rendered_but_not_skip_the_gate():
    """A renderer fix invalidates approved media; re-render must pass QC and approval again."""
    assert can_transition(JobState.APPROVED, JobState.RENDERING)
    assert not can_transition(JobState.APPROVED, JobState.PUBLISHED)
    assert not can_transition(JobState.APPROVED, JobState.READY_FOR_APPROVAL)


def test_re_render_from_approved_does_not_skip_qc_or_reapproval():
    """The only allowed exit from APPROVED (besides publish) is RENDERING.

    Re-rendering replaces the media the operator approved, so the job must pass
    technical QC, the editorial gate and a fresh approval decision again.
    """
    assert TRANSITIONS[JobState.APPROVED] == {
        JobState.PRIVATE_UPLOAD, JobState.RENDERING, JobState.CANCELLED,
    }
