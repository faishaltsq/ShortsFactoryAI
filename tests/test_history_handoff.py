"""Production history must reach the research and topic prompts, not be recomputed per candidate."""
from packages.core.config import get_settings
from packages.core.orchestration import JobState, JobStore
from packages.core.pipeline import PipelineRunner
from packages.core.research import production_history


def _store(tmp_path) -> JobStore:
    return JobStore(tmp_path / "factory.db", tmp_path / "jobs")


def _seed_script(store: JobStore, job_id: str, *, title: str, genre: str) -> None:
    from packages.core.schemas import Script

    store.write_artifact(job_id, "script.json", Script.model_validate({
        "title": title,
        "genre": genre,
        "content_type": "fictional",
        "segments": [
            {"kind": "hook", "text": f"Hook untuk {title}."},
            {"kind": "payoff", "text": f"Payoff untuk {title}."},
        ],
    }).model_dump(mode="json"))


def _stamp(store: JobStore, job_id: str, updated_at: str) -> None:
    """Pin updated_at so most-recent-first ordering is testable (it is second-granular)."""
    with store._connect() as conn:
        conn.execute("UPDATE jobs SET updated_at=? WHERE id=?", (updated_at, job_id))


def test_history_reads_titles_and_genres_of_earlier_jobs(tmp_path):
    store = _store(tmp_path)
    first = store.create(title="Beton Romawi")
    _seed_script(store, first.id, title="Beton Romawi", genre="history")
    second = store.create(title="Cahaya Matahari")
    _seed_script(store, second.id, title="Cahaya Matahari", genre="science")
    current = store.create(title="job sekarang")

    history = production_history(store, exclude_job_id=current.id)

    assert {"Beton Romawi", "Cahaya Matahari"} <= set(history.titles)
    assert set(history.genres) == {"history", "science"}
    assert "job sekarang" not in history.titles, "the job being researched is excluded"


def test_history_lists_most_recent_jobs_first(tmp_path):
    store = _store(tmp_path)
    older = store.create(title="Lebih lama")
    _seed_script(store, older.id, title="Lebih lama", genre="history")
    newer = store.create(title="Lebih baru")
    _seed_script(store, newer.id, title="Lebih baru", genre="science")
    _stamp(store, older.id, "2026-01-01T00:00:00+00:00")
    _stamp(store, newer.id, "2026-02-01T00:00:00+00:00")
    current = store.create(title="job sekarang")

    history = production_history(store, exclude_job_id=current.id)

    assert history.titles[:2] == ["Lebih baru", "Lebih lama"]
    assert history.genres[:2] == ["science", "history"]


def test_history_skips_unreadable_jobs_instead_of_failing(tmp_path):
    store = _store(tmp_path)
    broken = store.create(title="Rusak")
    (store.artifact_root(broken.id) / "script.json").write_text("{}", encoding="utf-8")
    (store.artifact_root(broken.id) / "topic.json").write_text("bukan json", encoding="utf-8")
    healthy = store.create(title="Sehat")
    _seed_script(store, healthy.id, title="Sehat", genre="fiction")
    current = store.create(title="job sekarang")

    history = production_history(store, exclude_job_id=current.id)

    # The unreadable script contributes no genre, and its title is still readable
    # from the job row; nothing raises.
    assert "Sehat" in history.titles
    assert history.genres == ["fiction"]


def test_genre_falls_back_to_topic_artifact(tmp_path):
    store = _store(tmp_path)
    job = store.create(title="Hanya topik")
    store.write_artifact(job.id, "topic.json", {
        "selection": {"selected_topic_id": "t1", "rationale": "ok", "genre": "mystery",
                      "scores": {"originality": 5, "hook": 5, "verifiability": 5,
                                 "visual": 5, "genre_diversity": 5}},
        "topic": {"topic_id": "t1", "title": "Hanya topik", "genre": "mystery", "hook": "h",
                  "angle": "a", "sources": [], "verification": "needs_review",
                  "visual_potential": 5, "novelty": 5},
    })
    current = store.create(title="job sekarang")

    assert production_history(store, exclude_job_id=current.id).genres == ["mystery"]


def test_history_values_are_deduplicated_and_stable(tmp_path):
    store = _store(tmp_path)
    for title in ("Sama", "Sama", "Beda"):
        job = store.create(title=title)
        _seed_script(store, job.id, title=title, genre="science")
    current = store.create(title="job sekarang")

    first = production_history(store, exclude_job_id=current.id)
    second = production_history(store, exclude_job_id=current.id)

    assert first == second
    assert sorted(first.titles) == ["Beda", "Sama"]
    assert first.genres == ["science"]


def test_research_prompt_receives_history_and_payload_titles(tmp_path, monkeypatch):
    from packages.core.agents import ResearchAgent

    store = _store(tmp_path)
    earlier = store.create(title="Beton Romawi yang tahan laut")
    _seed_script(store, earlier.id, title="Beton Romawi yang tahan laut", genre="history")
    job = store.create(title="job sekarang", payload={"avoid_titles": ["Topik dari penjadwal"]})
    runner = PipelineRunner(store, get_settings(), force_mock=True)

    captured: dict = {}
    original = ResearchAgent.run

    def run(self, *, genres, avoid_titles, day_focus):
        captured["avoid"] = list(avoid_titles)
        captured["day_focus"] = day_focus
        return original(self, genres=genres, avoid_titles=avoid_titles, day_focus=day_focus)

    monkeypatch.setattr(ResearchAgent, "run", run)
    assert runner.run(job.id, stop_at=JobState.TOPIC_SELECTED).ok

    assert "Beton Romawi yang tahan laut" in captured["avoid"]
    assert "Topik dari penjadwal" in captured["avoid"]
    assert captured["day_focus"] == "job sekarang"


def test_topic_prompt_receives_recent_genres(tmp_path, monkeypatch):
    from packages.core.agents import TopicSelectionAgent

    store = _store(tmp_path)
    earlier = store.create(title="Beton Romawi")
    _seed_script(store, earlier.id, title="Beton Romawi", genre="history")
    job = store.create(title="job sekarang")
    runner = PipelineRunner(store, get_settings(), force_mock=True)

    captured: dict = {}
    original = TopicSelectionAgent.run

    def run(self, candidates, recent_genres):
        captured["recent"] = list(recent_genres)
        return original(self, candidates, recent_genres)

    monkeypatch.setattr(TopicSelectionAgent, "run", run)
    assert runner.run(job.id, stop_at=JobState.TOPIC_SELECTED).ok

    assert captured["recent"] == ["history"]


def test_job_without_history_still_researches(tmp_path):
    store = _store(tmp_path)
    job = store.create(title="job pertama")
    runner = PipelineRunner(store, get_settings(), force_mock=True)

    report = runner.run(job.id, stop_at=JobState.TOPIC_SELECTED)

    assert report.ok, report.as_dict()
    assert production_history(store, exclude_job_id=job.id).titles == []
