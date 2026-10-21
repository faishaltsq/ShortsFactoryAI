"""Adversarial source-retrieval tests; no external DNS or connections."""
import io
import socket
import ssl
import subprocess
import sys
import threading
import time
from pathlib import Path

import pytest

from packages.core.research import retrieval


@pytest.fixture(autouse=True)
def deny_external_network(monkeypatch):
    def forbidden(*args, **kwargs):
        raise AssertionError("test attempted external network access")

    monkeypatch.setattr(socket, "getaddrinfo", forbidden)
    monkeypatch.setattr(socket, "socket", forbidden)


@pytest.mark.parametrize("url", [
    "http://localhost/", "http://LOCALHOST./", "http://sub.localhost/",
    "http://localhost.localdomain/", "http://router.local/", "http://service.internal/",
    "http://metadata.google.internal/computeMetadata/v1/", "http://metadata.google/",
    "http://169.254.169.254/latest/meta-data/", "http://100.100.100.200/",
    "http://168.63.129.16/", "http://0.0.0.0/", "http://127.0.0.1/",
    "http://10.1.2.3/", "http://172.16.0.1/", "http://192.168.1.1/",
    "http://192.0.0.8/", "http://192.0.2.1/", "http://198.18.0.1/",
    "http://224.0.0.1/", "http://255.255.255.255/",
    "http://2130706433/", "http://127.1/", "http://0177.0.0.1/", "http://0x7f000001/",
    "http://[::1]/", "http://[::]/", "http://[fe80::1]/", "http://[fc00::1]/",
    "http://[::ffff:127.0.0.1]/", "http://[64:ff9b::7f00:1]/",
    "http://[2002:7f00:1::]/", "http://[2001:db8::1]/", "http://[ff02::1]/",
    "http://[fe80::1%25eth0]/", "http://user:synthetic-credential@example.com/",
    "https://@example.com/", "https://example.com:22/", "https://example.com:8443/",
    "https://example.com:80/", "http://example.com:443/", "https://example.com:0/",
    "https://example.com:65536/", "https://example.com:/", "https://[::1",
    "https://example.com\\@127.0.0.1/", "https://example.com/\r\nHost:localhost",
    "\thttps://example.com/", "https://%31%32%37.0.0.1/", "https://printer/",
    "https://[2606:4700:4700::1111]garbage/",
])
def test_unsafe_url_is_rejected_before_calling_fetcher(url):
    calls = []

    def fetcher(*args):
        calls.append(args)
        return 200, b"untrusted body"

    assert not retrieval.eligible_url(url)
    [source] = retrieval.fetch_sources([url], fetcher=fetcher)
    assert source.status == "skipped"
    assert source.text == ""
    assert calls == []


@pytest.mark.parametrize("url", [
    "https://example.com/", "http://example.com:80/", "https://example.com:443/",
    "https://nasa.gov/press", "https://8.8.8.8/", "https://[2606:4700:4700::1111]/",
])
def test_web_public_url_has_offline_syntactic_eligibility(url):
    assert retrieval.eligible_url(url)


def response_bytes(status=200, body=b"evidence", headers=None, *, length=True):
    headers = dict(headers or {})
    if length and "Content-Length" not in headers:
        headers["Content-Length"] = str(len(body))
    head = f"HTTP/1.1 {status} Test\r\n" + "".join(f"{key}: {value}\r\n" for key, value in headers.items())
    return head.encode("ascii") + b"\r\n" + body


class RecordingBytesIO(io.BytesIO):
    def __init__(self, raw):
        super().__init__(raw)
        self.read_sizes = []

    def read(self, size=-1):
        self.read_sizes.append(size)
        return super().read(size)

    def read1(self, size=-1):
        self.read_sizes.append(size)
        return super().read1(size)


class FakeSocket:
    def __init__(self, family, raw):
        self.family = family
        self.file = RecordingBytesIO(raw)
        self.connected = None
        self.sent = b""
        self.closed = False
        self.closed_event = threading.Event()
        self.timeouts = []
        self.connect_hook = None

    def settimeout(self, value):
        self.timeouts.append(value)

    def setsockopt(self, *args):
        pass

    def connect(self, address):
        self.connected = address
        if self.connect_hook:
            self.connect_hook()

    def do_handshake(self):
        pass

    def sendall(self, data):
        self.sent += data

    def makefile(self, *args):
        return self.file

    def shutdown(self, *args):
        self.closed = True
        self.closed_event.set()

    def close(self):
        self.closed = True
        self.closed_event.set()


@pytest.fixture()
def wire(monkeypatch):
    class Wire:
        responses = []
        sockets = []
        lookups = []
        answers = ["8.8.8.8"]
        stream_factory = None
        connect_hook = None

        def resolve(self, host, port, *args, **kwargs):
            self.lookups.append((host, port))
            addresses = self.answers(host) if callable(self.answers) else self.answers
            return [
                (socket.AF_INET6 if ":" in ip else socket.AF_INET, socket.SOCK_STREAM, socket.IPPROTO_TCP,
                 "", (ip, port, 0, 0) if ":" in ip else (ip, port))
                for ip in addresses
            ]

        def socket(self, family=socket.AF_INET, *args, **kwargs):
            assert self.responses, "unexpected connection"
            result = FakeSocket(family, self.responses.pop(0))
            result.connect_hook = self.connect_hook
            if self.stream_factory:
                result.file = self.stream_factory(result.file.getvalue(), result)
            self.sockets.append(result)
            return result

    result = Wire()
    monkeypatch.setattr(socket, "getaddrinfo", result.resolve)
    monkeypatch.setattr(socket, "socket", result.socket)
    return result


@pytest.mark.parametrize("unsafe_ip", [
    "127.0.0.1", "10.0.0.1", "169.254.169.254", "100.64.0.1", "192.0.0.8",
    "168.63.129.16", "::1", "fd00:ec2::254", "fe80::1", "::ffff:127.0.0.1",
    "64:ff9b::7f00:1", "2002:7f00:1::", "ff02::1", "2001:db8::1",
])
def test_every_dns_answer_must_be_public_before_any_connection(wire, unsafe_ip):
    wire.answers = ["8.8.8.8", unsafe_ip]
    wire.responses = [response_bytes()]

    [source] = retrieval.fetch_sources(["http://source.example/"])

    assert source.status == "error"
    assert source.text == ""
    assert wire.sockets == [], "one safe answer may not hide a later unsafe answer"


def test_empty_dns_answer_fails_closed(wire):
    wire.answers = []
    [source] = retrieval.fetch_sources(["http://source.example/"])
    assert source.status == "error"
    assert wire.sockets == []


def test_connection_is_pinned_to_the_validated_dns_answer(wire):
    def rebind_after_validation(host):
        return ["8.8.8.8"] if len(wire.lookups) == 1 else ["127.0.0.1"]

    wire.answers = rebind_after_validation
    wire.responses = [response_bytes()]

    status, body = retrieval.http_fetch("http://source.example/article?x=1#fragment")

    assert (status, body) == (200, b"evidence")
    assert wire.lookups == [("source.example", 80)], "the socket must not resolve the hostname again"
    [connection] = wire.sockets
    assert connection.connected == ("8.8.8.8", 80)
    assert b"Host: source.example\r\n" in connection.sent
    assert connection.sent.startswith(b"GET /article?x=1 HTTP/1.1\r\n")
    assert connection.closed


def test_public_ipv6_is_connected_as_validated_numeric_ipv6(wire):
    wire.responses = [response_bytes()]
    status, body = retrieval.http_fetch("http://[2606:4700:4700::1111]/")
    assert (status, body) == (200, b"evidence")
    assert wire.lookups == [], "a numeric literal does not require DNS"
    [connection] = wire.sockets
    assert connection.family == socket.AF_INET6
    assert connection.connected == ("2606:4700:4700::1111", 80, 0, 0)
    assert b"Host: [2606:4700:4700::1111]\r\n" in connection.sent


def test_tls_keeps_original_name_and_certificate_verification(wire, monkeypatch):
    wire.responses = [response_bytes()]
    original_context = ssl.create_default_context
    tls_calls = []

    class Context:
        def wrap_socket(self, sock, *, server_hostname, do_handshake_on_connect=True):
            tls_calls.append((sock.connected, server_hostname))
            return sock

    def verified_context():
        context = original_context()
        assert context.check_hostname is True
        assert context.verify_mode == ssl.CERT_REQUIRED
        return Context()

    monkeypatch.setattr(ssl, "create_default_context", verified_context)
    monkeypatch.setenv("HTTPS_PROXY", "http://127.0.0.1:9999")
    monkeypatch.setenv("HTTP_PROXY", "http://127.0.0.1:9999")
    monkeypatch.setenv("ALL_PROXY", "http://127.0.0.1:9999")

    assert retrieval.http_fetch("https://source.example/") == (200, b"evidence")
    assert wire.lookups == [("source.example", 443)]
    assert tls_calls == [(("8.8.8.8", 443), "source.example")]
    assert b"Host: source.example\r\n" in wire.sockets[0].sent


@pytest.mark.parametrize("location", [
    "http://127.0.0.1/", "http://169.254.169.254/", "http://[::1]/",
    "//10.0.0.1/", "file:///local-file", "http://user:synthetic-credential@source.example/",
    "http://source.example:8080/", "http://[::1", "http://source.example/\tbad",
])
def test_redirect_to_unsafe_target_never_connects(wire, location):
    wire.responses = [response_bytes(302, headers={"Location": location}), response_bytes()]
    [source] = retrieval.fetch_sources(["http://source.example/"])
    assert source.status == "error"
    assert source.text == ""
    assert len(wire.sockets) == 1
    assert wire.sockets[0].closed


def test_redirect_hostname_has_its_dns_revalidated(wire):
    wire.answers = lambda host: ["8.8.8.8"] if host == "source.example" else ["192.168.1.1"]
    wire.responses = [response_bytes(307, headers={"Location": "http://redirect.example/"}), response_bytes()]
    [source] = retrieval.fetch_sources(["http://source.example/"])
    assert source.status == "error"
    assert wire.lookups == [("source.example", 80), ("redirect.example", 80)]
    assert len(wire.sockets) == 1


def test_same_host_redirect_revalidates_rebound_dns(wire):
    wire.answers = lambda host: ["8.8.8.8"] if len(wire.lookups) == 1 else ["127.0.0.1"]
    wire.responses = [response_bytes(301, headers={"Location": "/next"}), response_bytes()]
    [source] = retrieval.fetch_sources(["http://source.example/"])
    assert source.status == "error"
    assert len(wire.lookups) == 2
    assert len(wire.sockets) == 1


@pytest.mark.parametrize("redirect_status", [301, 302, 303, 307, 308])
def test_public_relative_redirect_is_followed(wire, redirect_status):
    wire.responses = [response_bytes(redirect_status, headers={"Location": "../article?x=1"}), response_bytes()]
    assert retrieval.http_fetch("http://source.example/old/path") == (200, b"evidence")
    assert len(wire.sockets) == 2
    assert wire.sockets[1].sent.startswith(b"GET /article?x=1 HTTP/1.1\r\n")
    assert all(connection.closed for connection in wire.sockets)


def test_redirect_chain_has_a_hard_hop_cap(wire):
    wire.responses = [response_bytes(302, headers={"Location": f"/hop-{index}"}) for index in range(20)]
    [source] = retrieval.fetch_sources(["http://source.example/"])
    assert source.status == "error"
    assert 1 < len(wire.sockets) <= 6
    assert all(connection.closed for connection in wire.sockets)


@pytest.mark.parametrize("status", [300, 302, 304, 404, 429, 500, 503])
def test_terminal_http_status_is_not_misreported_as_success(wire, status):
    wire.responses = [response_bytes(status)]
    [source] = retrieval.fetch_sources(["http://source.example/"])
    assert source.status == f"http_{status}"
    assert wire.sockets[0].closed


@pytest.mark.parametrize("length", [True, False])
def test_oversized_network_body_is_rejected_not_truncated(wire, length):
    wire.responses = [response_bytes(body=b"123456789", length=length)]
    with pytest.raises(retrieval.RetrievalError, match="byte limit"):
        retrieval.http_fetch("http://source.example/", max_bytes=8)
    assert wire.sockets[0].closed
    assert all(0 < size <= 9 for size in wire.sockets[0].file.read_sizes)
    if length:
        assert wire.sockets[0].file.read_sizes == [], "Content-Length can reject before reading the body"


def test_injected_fetcher_cannot_bypass_the_byte_limit():
    [source] = retrieval.fetch_sources(["http://source.example/"], max_bytes=8,
                                       fetcher=lambda *args: (200, b"123456789"))
    assert source.status == "error"
    assert source.text == "" and source.sha256 == "" and source.chars == 0
    with pytest.raises(retrieval.RetrievalError):
        retrieval.retrieve_or_raise(["http://source.example/"], max_bytes=8,
                                    fetcher=lambda *args: (200, b"123456789"))


def test_network_body_at_exact_limit_is_not_truncated(wire):
    wire.responses = [response_bytes(body=b"12345678", length=False)]
    assert retrieval.http_fetch("http://source.example/", max_bytes=8) == (200, b"12345678")


def test_byte_limit_cannot_be_raised_above_the_hard_cap():
    bounds = []

    def fetcher(url, timeout, max_bytes):
        bounds.append(max_bytes)
        return 200, b"evidence"

    [source] = retrieval.fetch_sources(["http://source.example/"], fetcher=fetcher, max_bytes=10**12)
    assert source.status == "ok"
    assert bounds == [retrieval.DEFAULT_MAX_BYTES]


@pytest.mark.parametrize("limit", [0, -1, 1.5, True, float("nan"), float("inf")])
def test_invalid_byte_limits_are_rejected_before_fetching(limit):
    with pytest.raises(ValueError):
        retrieval.fetch_sources(["http://source.example/"], max_bytes=limit,
                                 fetcher=lambda *args: pytest.fail("invalid bounds reached fetcher"))


@pytest.mark.parametrize("value", ["invalid", "-1", "4, 4"])
def test_invalid_content_length_cannot_be_treated_as_verified(wire, value):
    wire.responses = [response_bytes(headers={"Content-Length": value})]
    [source] = retrieval.fetch_sources(["http://source.example/"])
    assert source.status == "error"
    assert source.text == ""


def test_incomplete_content_length_is_an_error(wire):
    wire.responses = [response_bytes(body=b"short", headers={"Content-Length": "100"})]
    [source] = retrieval.fetch_sources(["http://source.example/"])
    assert source.status == "error"
    assert source.text == ""


@pytest.mark.parametrize("status", [200, 206])
def test_partial_source_never_becomes_whole_source_evidence(wire, status):
    wire.responses = [response_bytes(status, headers={"Content-Range": "bytes 0-7/1000"})]
    [source] = retrieval.fetch_sources(["http://source.example/"])
    assert source.status != "ok"
    if status == 206:
        assert source.status == "http_206"


def test_unsolicited_compression_is_not_evidence(wire):
    wire.responses = [response_bytes(body=b"compressed-data", headers={"Content-Encoding": "gzip"})]
    [source] = retrieval.fetch_sources(["http://source.example/"])
    assert source.status == "error" and source.text == ""


def test_clean_text_is_not_silently_truncated_into_verified_evidence():
    [source] = retrieval.fetch_sources(["http://source.example/"],
                                       fetcher=lambda *args: (200, b"x" * (retrieval.MAX_TEXT_CHARS + 1)))
    assert source.status == "error"
    assert source.text == "" and source.sha256 == ""


@pytest.mark.parametrize("status,body", [("200", b"text"), (True, b"text"), (0, b"text"),
                                        (600, b"text"), (200, "not bytes"), (200, None)])
def test_invalid_fetcher_output_fails_closed(status, body):
    [source] = retrieval.fetch_sources(["http://source.example/"], fetcher=lambda *args: (status, body))
    assert source.status == "error"
    assert source.text == ""


def test_injected_fetcher_has_a_wall_clock_deadline():
    release = threading.Event()
    finished = threading.Event()

    def blocked_fetcher(*args):
        try:
            release.wait(0.5)
            return 200, b"late evidence"
        finally:
            finished.set()

    started = time.monotonic()
    try:
        [source] = retrieval.fetch_sources(["http://source.example/"], fetcher=blocked_fetcher, timeout=0.04)
        assert time.monotonic() - started < 0.3
        assert source.status == "error"
        assert "TimeoutError" in source.error
        assert source.text == ""
    finally:
        release.set()
        assert finished.wait(1)


def test_dns_deadline_returns_without_a_late_connection(wire, monkeypatch):
    release = threading.Event()
    finished = threading.Event()
    resolver = wire.resolve

    def slow_dns(*args, **kwargs):
        try:
            release.wait(0.5)
            return resolver(*args, **kwargs)
        finally:
            finished.set()

    monkeypatch.setattr(socket, "getaddrinfo", slow_dns)
    wire.responses = [response_bytes()]
    started = time.monotonic()
    try:
        with pytest.raises(TimeoutError):
            retrieval.http_fetch("http://source.example/", timeout=0.04)
        assert time.monotonic() - started < 0.3
        assert wire.sockets == []
    finally:
        release.set()
        assert finished.wait(1)
    # Let the resolver worker observe expiration; it must not start a socket afterward.
    time.sleep(0.02)
    assert wire.sockets == []


def test_slow_headers_are_aborted_by_the_total_deadline(wire):
    class SlowHeaders(RecordingBytesIO):
        def readline(self, size=-1):
            wire.sockets[0].closed_event.wait(0.5)
            return super().readline(size)

    wire.stream_factory = lambda raw, sock: SlowHeaders(raw)
    wire.responses = [response_bytes()]
    started = time.monotonic()
    with pytest.raises(TimeoutError):
        retrieval.http_fetch("http://source.example/", timeout=0.04)
    assert time.monotonic() - started < 0.3
    assert wire.sockets[0].closed


def test_slow_trickle_body_cannot_reset_the_total_deadline(wire):
    class TrickleBody(RecordingBytesIO):
        def read1(self, size=-1):
            time.sleep(0.02)
            return super().read1(min(size, 1))

    wire.stream_factory = lambda raw, sock: TrickleBody(raw)
    wire.responses = [response_bytes(body=b"x" * 50)]
    started = time.monotonic()
    with pytest.raises(TimeoutError):
        retrieval.http_fetch("http://source.example/", timeout=0.06)
    assert time.monotonic() - started < 0.3
    assert wire.sockets[0].closed


def test_redirect_hops_share_one_deadline(wire):
    wire.connect_hook = lambda: time.sleep(0.025)
    wire.responses = [response_bytes(302, headers={"Location": f"/hop-{index}"}) for index in range(10)]
    started = time.monotonic()
    with pytest.raises(TimeoutError):
        retrieval.http_fetch("http://source.example/", timeout=0.06)
    assert time.monotonic() - started < 0.3
    assert len(wire.sockets) <= 3
    assert all(connection.closed for connection in wire.sockets)


def test_timeout_cannot_exceed_the_hard_cap():
    bounds = []

    def fetcher(url, timeout, max_bytes):
        bounds.append(timeout)
        return 200, b"evidence"

    [source] = retrieval.fetch_sources(["http://source.example/"], fetcher=fetcher, timeout=10**12)
    assert source.status == "ok"
    assert 0 < bounds[0] <= retrieval.DEFAULT_TIMEOUT_S


@pytest.mark.parametrize("timeout", [0, -1, True, float("nan"), float("inf"), None, "15"])
def test_invalid_timeout_is_rejected_before_fetching(timeout):
    with pytest.raises(ValueError):
        retrieval.fetch_sources(["http://source.example/"], timeout=timeout,
                                 fetcher=lambda *args: pytest.fail("invalid timeout reached fetcher"))


@pytest.mark.parametrize("exception_type", [ValueError, OSError, TimeoutError, ssl.SSLCertVerificationError])
def test_failure_records_only_exception_type(exception_type):
    def broken(*args):
        raise exception_type("synthetic-sensitive-message-must-not-be-recorded")

    [source] = retrieval.fetch_sources(["http://source.example/"], fetcher=broken)
    assert source.status == "error"
    assert source.error == exception_type.__name__
    assert "synthetic-sensitive-message" not in str(source.as_dict(include_text=True))


def test_exception_message_is_never_even_formatted():
    class OpaqueFailure(Exception):
        def __str__(self):
            raise AssertionError("untrusted exception text was evaluated")

    def broken(*args):
        raise OpaqueFailure()

    [source] = retrieval.fetch_sources(["http://source.example/"], fetcher=broken)
    assert source.error == "OpaqueFailure"


def test_rejected_userinfo_is_not_persisted_or_echoed():
    url = "http://synthetic-user:synthetic-sensitive-marker@source.example/path"
    [source] = retrieval.fetch_sources([url], fetcher=lambda *args: pytest.fail("credentials reached fetcher"))
    assert source.status == "skipped"
    assert "synthetic-sensitive-marker" not in str(source.as_dict(include_text=True))
    with pytest.raises(retrieval.RetrievalError) as excinfo:
        retrieval.retrieve_or_raise([url])
    assert "synthetic-sensitive-marker" not in str(excinfo.value)


def test_timed_out_workers_have_a_hard_concurrency_bound(monkeypatch):
    slots = threading.BoundedSemaphore(2)
    monkeypatch.setattr(retrieval, "_FETCH_SLOTS", slots)
    release = threading.Event()
    finished = [threading.Event(), threading.Event()]
    calls = []

    def blocked(*args):
        index = len(calls)
        calls.append(args)
        try:
            release.wait(1)
            return 200, b"late"
        finally:
            finished[index].set()

    try:
        for _ in range(3):
            [source] = retrieval.fetch_sources(["http://source.example/"], fetcher=blocked, timeout=0.03)
            assert source.status == "error"
        assert len(calls) == 2, "abandoned DNS/fetcher workers must not accumulate without a cap"
        assert source.error == "RetrievalError"
    finally:
        release.set()
        assert all(event.wait(1) for event in finished)


def test_adversarial_markup_cannot_hold_the_gil_past_the_fetch_deadline():
    # A subprocess keeps this regression safe even if a future regex holds the GIL.
    code = ("from packages.core.research.retrieval import clean_text; "
            "assert clean_text(b'<script>' * 50000) == ''")
    result = subprocess.run([sys.executable, "-c", code], cwd=Path(__file__).resolve().parents[1],
                            capture_output=True, timeout=2, check=False)
    assert result.returncode == 0


@pytest.mark.parametrize("raw,expected", [
    (b"8\r\n12345678\r\n0\r\n\r\n", b"12345678"),
    (b"3\r\n123\r\n5\r\n45678\r\n0\r\n\r\n", b"12345678"),
])
def test_chunked_body_at_exact_limit_is_complete(wire, raw, expected):
    wire.responses = [response_bytes(body=raw, headers={"Transfer-Encoding": "chunked"}, length=False)]
    assert retrieval.http_fetch("http://source.example/", max_bytes=8) == (200, expected)


def test_chunked_body_cannot_bypass_size_cap(wire):
    raw = b"9\r\n123456789\r\n0\r\n\r\n"
    wire.responses = [response_bytes(body=raw, headers={"Transfer-Encoding": "chunked"}, length=False)]
    with pytest.raises(retrieval.RetrievalError, match="byte limit"):
        retrieval.http_fetch("http://source.example/", max_bytes=8)
    assert wire.sockets[0].closed


def test_incomplete_chunked_body_is_not_verified(wire):
    wire.responses = [response_bytes(body=b"8\r\n12345678\r\n", headers={"Transfer-Encoding": "chunked"}, length=False)]
    [source] = retrieval.fetch_sources(["http://source.example/"])
    assert source.status == "error"
    assert source.text == ""


def test_tls_certificate_failure_is_not_retried_without_verification(wire, monkeypatch):
    class Context:
        def wrap_socket(self, *args, **kwargs):
            raise ssl.SSLCertVerificationError("synthetic-sensitive-marker")

    monkeypatch.setattr(ssl, "create_default_context", Context)
    wire.responses = [response_bytes()]
    [source] = retrieval.fetch_sources(["https://source.example/"])
    assert source.status == "error"
    assert source.error == "SSLCertVerificationError"
    assert len(wire.sockets) == 1
    assert wire.sockets[0].closed and not wire.sockets[0].sent


def test_tls_handshake_is_part_of_the_total_deadline(wire, monkeypatch):
    class Context:
        def wrap_socket(self, sock, *, server_hostname, do_handshake_on_connect):
            assert do_handshake_on_connect is False

            def stalled_handshake():
                sock.closed_event.wait(5.0)

            sock.do_handshake = stalled_handshake
            return sock

    monkeypatch.setattr(ssl, "create_default_context", Context)
    wire.responses = [response_bytes()]
    started = time.monotonic()
    with pytest.raises(TimeoutError):
        retrieval.http_fetch("https://source.example/", timeout=0.5)
    assert time.monotonic() - started < 3.0
    assert wire.sockets[0].closed and not wire.sockets[0].sent


def test_connect_is_part_of_the_total_deadline(wire):
    wire.connect_hook = lambda: wire.sockets[0].closed_event.wait(5.0)
    wire.responses = [response_bytes()]
    started = time.monotonic()
    with pytest.raises(TimeoutError):
        retrieval.http_fetch("http://source.example/", timeout=0.5)
    assert time.monotonic() - started < 3.0
    assert wire.sockets[0].closed and not wire.sockets[0].sent


@pytest.mark.parametrize("record", [
    (socket.AF_INET, socket.SOCK_STREAM, socket.IPPROTO_TCP, "", ("8.8.8.8", 22)),
    (socket.AF_INET, socket.SOCK_STREAM, socket.IPPROTO_TCP, "", ("2606:4700:4700::1111", 80)),
    (socket.AF_INET6, socket.SOCK_STREAM, socket.IPPROTO_TCP, "", ("2606:4700:4700::1111", 80, 0, 4)),
    (socket.AF_INET6, socket.SOCK_STREAM, socket.IPPROTO_TCP, "", ("2606:4700:4700::1111%4", 80, 0, 0)),
])
def test_malformed_dns_sockaddr_never_reaches_connect(wire, monkeypatch, record):
    monkeypatch.setattr(socket, "getaddrinfo", lambda *args: [record])
    [source] = retrieval.fetch_sources(["http://source.example/"])
    assert source.status == "error" and source.text == ""
    assert wire.sockets == []


@pytest.mark.parametrize("url", ["http://[::1]/", "http://127.0.0.1/", "https://user:synthetic@example.com/"])
def test_direct_http_fetch_also_enforces_url_policy(url):
    with pytest.raises(retrieval.RetrievalError):
        retrieval.http_fetch(url)
