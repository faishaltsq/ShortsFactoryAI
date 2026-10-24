"""One owner map and one stop list, shared by the runner, observer, CLI and API."""
from packages.core import activity
from packages.core.observability import lifecycle
from packages.core.orchestration.states import STOP_POINTS, JobState


def test_lifecycle_imports_the_shared_owner_map_instead_of_copying_it():
    assert lifecycle.STAGE_AGENTS is activity.STAGE_AGENTS


def test_every_runner_stage_has_exactly_one_owner():
    from packages.core.orchestration.states import ARTIFACT_FOR_STATE
    from packages.core.pipeline import PipelineRunner

    runner = PipelineRunner.__new__(PipelineRunner)
    for state, artifact, _ in PipelineRunner._stages(runner):
        assert state.value in activity.STAGE_AGENTS, f"{state.value} ({artifact}) has no owning agent"
        if state in ARTIFACT_FOR_STATE:
            assert ARTIFACT_FOR_STATE[state] == artifact, f"{state.value} disagrees on its artifact"


def test_derived_stages_are_owned():
    assert activity.STAGE_AGENTS["DRAFT_QC"] == "QualityAgent"
    assert activity.STAGE_AGENTS["METADATA"] == "MetadataAgent"
    assert activity.STAGE_AGENTS["THUMBNAIL"] == "RenderAgent"


def test_quality_owns_the_deterministic_editorial_gate():
    # The editorial gate reads written artifacts and asks no model, so it is a
    # QualityAgent stage, not MetadataAgent's.
    assert activity.STAGE_AGENTS["EDITORIAL_QC"] == "QualityAgent"


def test_render_owns_technical_qc_because_the_same_process_checks_it():
    assert activity.STAGE_AGENTS["TECHNICAL_QC"] == "RenderAgent"


def test_owners_are_known_agents():
    from packages.core.activity import AgentId

    allowed = set(AgentId.__args__)
    assert set(activity.STAGE_AGENTS.values()) <= allowed


def test_runner_and_api_share_one_stop_list():
    from packages.core.pipeline import PipelineRunner

    runner = PipelineRunner.__new__(PipelineRunner)
    runner_stops = {state.value for state, _, _ in PipelineRunner._stages(runner)}
    assert set(STOP_POINTS.values()) <= runner_stops
    assert STOP_POINTS["render"] is JobState.TECHNICAL_QC


def test_cli_uses_the_shared_stop_list():
    import importlib.util
    from pathlib import Path

    root = Path(__file__).resolve().parents[1]
    spec = importlib.util.spec_from_file_location("run_pipeline_cli", root / "scripts" / "run_pipeline.py")
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)

    assert module.STOP_POINTS is STOP_POINTS
    assert not hasattr(module, "STOPS")
