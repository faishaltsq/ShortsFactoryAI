from packages.core.research import similarity, trigrams
from packages.core.research.originality import DEFAULT_THRESHOLD, PriorScript, check_originality, prior_scripts_from
from packages.core.orchestration import JobStore

LONG_A = (
    "Cahaya matahari butuh delapan menit untuk sampai ke bumi, dan yang kamu lihat "
    "sekarang sudah berjalan jauh sebelum kamu membuka mata. Setiap kilau datang dari "
    "masa lalu yang tidak bisa dikejar lagi."
)
LONG_B = (
    "Resep soto betawi pakai santan, serai, dan kentang yang direbus pelan sampai "
    "kuahnya mengental. Sajikan panas dengan nasi putih dan jeruk limau di sampingnya."
)


def test_trigrams_capture_word_sequences():
    grams = trigrams("satu dua tiga empat")
    assert grams == {"satu dua tiga", "dua tiga empat"}


def test_trigrams_fall_back_for_short_texts():
    assert trigrams("matahari") == {"matahari"}
    assert trigrams("matahari hangat") == {"matahari hangat"}
    assert trigrams("") == set()


def test_identical_scripts_score_one():
    assert similarity(LONG_A, LONG_A) == 1.0


def test_unrelated_scripts_score_low():
    assert similarity(LONG_A, LONG_B) < 0.1


def test_empty_side_scores_zero():
    assert similarity("", LONG_A) == 0.0


def test_report_flags_a_duplicate_when_enforced():
    prior = [PriorScript(job_id="a" * 16, title="Cahaya Lalu", text=LONG_A)]
    report = check_originality(LONG_A, prior, threshold=DEFAULT_THRESHOLD, enforced=True)
    assert report.verdict == "too_similar"
    assert report.too_similar
    assert report.max_similarity == 1.0
    assert report.nearest_job_id == "a" * 16
    assert report.compared == 1
    assert report.enforced is True


def test_distinct_script_passes_the_gate():
    prior = [PriorScript(job_id="b" * 16, title="Soto Betawi", text=LONG_B)]
    report = check_originality(LONG_A, prior)
    assert report.verdict == "original"
    assert not report.too_similar
    assert report.max_similarity < report.threshold


def test_no_history_reports_original_with_reason():
    report = check_originality(LONG_A, [])
    assert report.verdict == "original"
    assert report.compared == 0
    assert "no earlier script" in report.note


def test_high_threshold_can_be_passed_deliberately():
    prior = [PriorScript(job_id="c" * 16, title="Mirip", text=LONG_A + " penutup.")]
    report = check_originality(LONG_A, prior, threshold=1.1, enforced=True)
    assert report.verdict == "original"


def test_prior_scripts_skip_jobs_without_a_script(tmp_path):
    store = JobStore(tmp_path / "factory.db", tmp_path / "jobs")
    store.create(title="tanpa naskah")  # missing script.json must be skipped, not fatal
    filled = store.create(title="ada naskah")
    store.write_artifact(
        filled.id,
        "script.json",
        {
            "title": "Ada Naskah",
            "genre": "science",
            "content_type": "fictional",
            "segments": [
                {"kind": "hook", "text": "Resep soto betawi"},
                {"kind": "body", "text": LONG_B},
            ],
        },
    )
    prior = prior_scripts_from(store, exclude_job_id="z" * 16)
    assert [p.job_id for p in prior] == [filled.id], "a job without script.json is skipped without failing the check"
    assert LONG_B in prior[0].text


def test_current_job_is_excluded_from_its_own_comparison(tmp_path):
    store = JobStore(tmp_path / "factory.db", tmp_path / "jobs")
    job = store.create(title="diri sendiri")
    store.write_artifact(
        job.id,
        "script.json",
        {
            "title": "Diri Sendiri",
            "genre": "science",
            "content_type": "fictional",
            "segments": [
                {"kind": "hook", "text": "Cahaya yang kamu lihat"},
                {"kind": "body", "text": LONG_A},
            ],
        },
    )
    assert prior_scripts_from(store, exclude_job_id=job.id) == []
