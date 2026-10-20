import sys


def test_remotion_counters_are_monotonic_and_never_claim_validation():
    from packages.core.media.progress import RemotionProgress

    parser = RemotionProgress(900)
    assert parser.feed("Rendered 450/900, time remaining: 1s\n")[0].percent == 45
    assert parser.feed("Rendered 100/900\nRendered 450/900\n") == []
    assert parser.feed("Rendered 9999/900\nRendered 10/20\n") == []
    assert parser.feed("Encoded 9") == []
    update = parser.feed("00/900\n")[0]
    assert update.phase == "encoded" and update.completed == update.total == 900
    assert update.percent == 99
    assert parser.feed("Encoded 900/900\n") == []


def test_media_output_callback_observes_real_subprocess_output(tmp_path):
    from packages.core.media.process import run_checked

    chunks = []
    log = tmp_path / "progress.log"
    run_checked([sys.executable, "-u", "-c", "print('Rendered 5/10'); print('Encoded 10/10')"],
                log_path=log, timeout=5, on_output=chunks.append)
    assert "Rendered 5/10" in "".join(chunks)
    assert "Encoded 10/10" in "".join(chunks)
    assert "Encoded 10/10" in log.read_text(encoding="utf-8")
