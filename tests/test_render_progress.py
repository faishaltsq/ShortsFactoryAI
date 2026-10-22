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


def test_remotion_port_skips_a_port_that_already_answers():
    """A port another process answers on must never be handed to the preview server.

    On Windows a wildcard listener leaves a plain bind succeeding, which is why Remotion's own
    probe accepts a busy port and Chrome then loads the foreign page instead of the bundle.
    """
    import socket

    from packages.core.media.process import _port_is_free, free_remotion_port

    listener = socket.socket(socket.AF_INET, socket.SOCK_STREAM)
    listener.bind(("127.0.0.1", 0))
    listener.listen(1)
    busy_port = listener.getsockname()[1]
    try:
        assert _port_is_free(busy_port) is False
        chosen = free_remotion_port()
        assert chosen != busy_port and chosen >= 1024 and _port_is_free(chosen) is True
    finally:
        listener.close()
    assert _port_is_free(busy_port) is True
