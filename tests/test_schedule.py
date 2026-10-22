"""Schedule projection: operator-facing status per job, derived from persisted state."""
import json
from datetime import datetime, timedelta, timezone

import pytest

from packages.core.observability.schedule import ScheduleService
from packages.core.orchestration.jobstore import JobStore
from packages.core.orchestration.states import JobState


@pytest.fixture()
def store(tmp_path):
    return JobStore(tmp_path / "factory.db", tmp_path)


def _artifact(store, job_id, name, data):
    store.write_artifact(job_id, name, data)


def _topic(genre="science"):
    return {"selection": {"selected_topic_id": "t1", "rationale": "x", "genre": genre,
                          "scores": {"originality": 5, "hook": 5, "verifiability": 5, "visual": 5, "genre_diversity": 5}},
            "topic": {"topic_id": "t1", "title": "Kenapa langit biru", "genre": genre, "hook": "h", "angle": "a",
                      "sources": [{"title": "s1"}, {"title": "s2"}]}}


def test_statuses_cover_ongoing_researching_and_upcoming(store):
    now = datetime.now(timezone.utc)

    research = store.create(title="Riset", state=JobState.IDEA_DISCOVERY)
    ongoing = store.create(title="Produksi", state=JobState.IDEA_DISCOVERY)
    for state in (JobState.TOPIC_SELECTED, JobState.SCRIPT_GENERATED, JobState.CREATIVE_REVIEW,
                  JobState.STORYBOARD_READY, JobState.ASSETS_READY, JobState.AUDIO_READY):
        store.transition(ongoing.id, state)
    _artifact(store, ongoing.id, "storyboard.json",
              {"id": "sb", "scenes": [{"sceneId": "s1", "template": "KineticTypography", "segment": "hook",
                                       "startFrame": 0, "durationInFrames": 300}]})

    upcoming = store.create(title="Nanti", state=JobState.IDEA_DISCOVERY,
                            payload={"due_at": (now + timedelta(days=2)).isoformat()})

    service = ScheduleService(store)
    rows = {row["job_id"]: row for row in service.entries()["entries"]}

    assert rows[research.id]["status"] == "RESEARCHING"
    assert rows[ongoing.id]["status"] == "ON GOING"
    assert rows[upcoming.id]["status"] == "UPCOMING"


def test_upcoming_requires_no_dispatch_attempt_and_a_future_due_time(store):
    now = datetime.now(timezone.utc)
    future = store.create(title="Depan", state=JobState.IDEA_DISCOVERY,
                          payload={"due_at": (now + timedelta(hours=5)).isoformat()})
    past = store.create(title="Lewat", state=JobState.IDEA_DISCOVERY,
                        payload={"due_at": (now - timedelta(hours=5)).isoformat()})

    service = ScheduleService(store)
    rows = {row["job_id"]: row for row in service.entries()["entries"]}

    assert rows[future.id]["status"] == "UPCOMING"
    # Its due time already passed, so it is being worked on, not waiting.
    assert rows[past.id]["status"] == "RESEARCHING"


def test_terminal_states_are_reported_separately(store):
    published = store.create(title="Terbit", state=JobState.IDEA_DISCOVERY)
    for state in (JobState.TOPIC_SELECTED, JobState.SCRIPT_GENERATED, JobState.CREATIVE_REVIEW,
                  JobState.STORYBOARD_READY, JobState.ASSETS_READY, JobState.AUDIO_READY,
                  JobState.RENDERING, JobState.TECHNICAL_QC, JobState.EDITORIAL_QC,
                  JobState.READY_FOR_APPROVAL, JobState.APPROVED, JobState.PRIVATE_UPLOAD,
                  JobState.SCHEDULED, JobState.PUBLISHED):
        store.transition(published.id, state)
    failed = store.create(title="Gagal", state=JobState.IDEA_DISCOVERY)
    store.transition(failed.id, JobState.FAILED, error="render validation failed")
    rejected = store.create(title="Ditolak", state=JobState.IDEA_DISCOVERY)
    store.transition(rejected.id, JobState.TOPIC_SELECTED)
    store.transition(rejected.id, JobState.SCRIPT_GENERATED)
    store.transition(rejected.id, JobState.CREATIVE_REVIEW)
    store.transition(rejected.id, JobState.REJECTED)

    service = ScheduleService(store)
    rows = {row["job_id"]: row for row in service.entries()["entries"]}

    assert rows[published.id]["status"] == "SELESAI"
    assert rows[failed.id]["status"] == "GAGAL"
    assert "render validation failed" in rows[failed.id]["next_action"]
    assert rows[rejected.id]["status"] == "TERTAHAN"


def test_content_description_comes_from_real_artifacts(store):
    job = store.create(title="Judul mentah", state=JobState.IDEA_DISCOVERY)
    for state in (JobState.TOPIC_SELECTED, JobState.SCRIPT_GENERATED, JobState.CREATIVE_REVIEW,
                  JobState.STORYBOARD_READY):
        store.transition(job.id, state)
    _artifact(store, job.id, "topic.json", _topic("history"))
    _artifact(store, job.id, "script.json", {"title": "Judul naskah", "genre": "history",
                                             "content_type": "factual", "verification_status": "needs_review",
                                             "segments": [{"kind": "hook", "text": "a"}, {"kind": "payoff", "text": "b"}]})
    _artifact(store, job.id, "storyboard.json",
              {"id": "sb", "scenes": [{"sceneId": "s1", "template": "HistoricalTimeline", "segment": "hook",
                                       "startFrame": 0, "durationInFrames": 300},
                                      {"sceneId": "s2", "template": "ParallaxStory", "segment": "payoff",
                                       "startFrame": 300, "durationInFrames": 300}]})

    row = next(entry for entry in ScheduleService(store).entries()["entries"] if entry["job_id"] == job.id)

    assert row["title"] == "Judul naskah"
    assert row["genre"] == "history"
    assert row["content_type"] == "factual"
    assert row["scene_count"] == 2
    assert row["templates"] == ["HistoricalTimeline", "ParallaxStory"]
    assert row["sources"] == 2
    assert row["verification"] == "needs_review"


def test_a_failed_job_keeps_the_progress_it_earned(store):
    job = store.create(title="Setengah jalan", state=JobState.IDEA_DISCOVERY)
    for state in (JobState.TOPIC_SELECTED, JobState.SCRIPT_GENERATED, JobState.CREATIVE_REVIEW,
                  JobState.STORYBOARD_READY, JobState.ASSETS_READY, JobState.AUDIO_READY, JobState.RENDERING):
        store.transition(job.id, state)
    store.transition(job.id, JobState.FAILED, error="media command exited 1")

    row = next(entry for entry in ScheduleService(store).entries()["entries"] if entry["job_id"] == job.id)

    assert row["status"] == "GAGAL"
    assert row["state"] == "FAILED"
    assert row["progress"] > 0


def test_plan_slots_drive_upcoming_entries(store):
    from packages.core.orchestration.planner import ProductionPlanner

    plan = ProductionPlanner(store).plan_seven_days(
        start=datetime.now(timezone.utc) + timedelta(days=1),
        videos_per_day=2, genres=["science"], provider_mode="mock")

    entries = ScheduleService(store).entries()
    planned = {entry["job_id"] for entry in entries["entries"]}

    assert len(plan.slots) == 14
    assert all(slot.job_id in planned for slot in plan.slots)
    assert entries["counts"]["UPCOMING"] == 14
    assert all(entry["due_at"] for entry in entries["entries"])


def test_counts_and_order_are_stable(store):
    research = store.create(title="Riset", state=JobState.IDEA_DISCOVERY)
    ongoing = store.create(title="Produksi", state=JobState.IDEA_DISCOVERY)
    for state in (JobState.TOPIC_SELECTED, JobState.SCRIPT_GENERATED, JobState.CREATIVE_REVIEW,
                  JobState.STORYBOARD_READY):
        store.transition(ongoing.id, state)

    result = ScheduleService(store).entries()

    assert result["total"] == 2
    assert set(result["counts"]) == {"ON GOING", "RESEARCHING", "UPCOMING", "SELESAI", "GAGAL", "TERTAHAN"}
    assert [entry["status"] for entry in result["entries"]] == ["ON GOING", "RESEARCHING"]
    assert result["entries"][0]["job_id"] == ongoing.id
    assert result["entries"][1]["job_id"] == research.id


def test_schedule_reads_no_secret_into_its_output(store, monkeypatch):
    # Assembled at runtime so the repository's secret scanner does not match a fixture
    # that is only pretending to be a key.
    fake = "sk-" + "abcdefghijklmnopqrstuvwx"
    monkeypatch.setenv("DEEPSEEK_API_KEY", fake)
    job = store.create(title="Rahasia", state=JobState.IDEA_DISCOVERY, payload={"note": fake})
    store.transition(job.id, JobState.FAILED, error=f"failed with {fake}")

    row = next(entry for entry in ScheduleService(store).entries()["entries"] if entry["job_id"] == job.id)

    assert fake not in json.dumps(row)
