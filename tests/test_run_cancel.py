from packages.core.orchestration import JobState, JobStore
from packages.core.pipeline import PipelineRunner


def test_run_berhenti_ketika_cancel_flag(tmp_env, tmp_path):
    store = JobStore(tmp_env["db"], tmp_env["jobs"])
    job = store.create(title="batal dulu")
    runner = PipelineRunner(store, force_mock=True)
    calls = {"n": 0}

    def cancel_after_first() -> bool:
        calls["n"] += 1
        return calls["n"] > 1

    report = runner.run(job.id, stop_at=JobState.STORYBOARD_READY, cancelled=cancel_after_first)
    assert report.blocked_reason is not None and "batal" in report.blocked_reason.lower()
    assert len(report.stages) <= 2                      # berhenti di batas stage berikutnya
    assert store.get(job.id).state is not JobState.CANCELLED   # bukan state terminal
    assert calls["n"] >= 2
