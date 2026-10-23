from packages.core.orchestration.states import STOP_POINTS, JobState


def test_stop_points_cover_every_stage_the_merged_pipeline_can_stop_at():
    assert STOP_POINTS["research"] is JobState.TOPIC_SELECTED
    assert STOP_POINTS["storyboard"] is JobState.STORYBOARD_READY
    assert STOP_POINTS["render"] is JobState.TECHNICAL_QC
    assert STOP_POINTS["editorial"] is JobState.EDITORIAL_QC
    assert STOP_POINTS["approval"] is JobState.READY_FOR_APPROVAL
    assert set(STOP_POINTS) == {
        "research", "script", "creative", "storyboard",
        "audio", "render", "editorial", "approval",
    }