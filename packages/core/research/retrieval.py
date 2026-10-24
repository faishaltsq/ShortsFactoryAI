"""Fetch bounded, plain-text copies of the cited sources.

The page body is untrusted input: it is size-capped before it is read in full,
stripped of markup and control characters, and stored as evidence text. Nothing
here executes, evaluates or interprets page content.
"""
from __future__ import annotations

import hashlib
import http.client
import ipaddress
import math
import re
import socket
import ssl
import threading
import time
from concurrent.futures import Future
from dataclasses import dataclass
from html.parser import HTMLParser
from typing import Callable, TypeVar
from urllib.parse import quote, urljoin, urlsplit

DEFAULT_MAX_BYTES = 512 * 1024
DEFAULT_TIMEOUT_S = 15.0
DEFAULT_MAX_SOURCES = 5
MAX_TEXT_CHARS = 200_000
MAX_URL_CHARS = 8192
MAX_REDIRECTS = 5
MAX_FETCH_WORKERS = 8
_FETCH_SLOTS = threading.BoundedSemaphore(MAX_FETCH_WORKERS)
_T = TypeVar("_T")
_REDIRECT_STATUSES = {301, 302, 303, 307, 308}

_INVALID_URL_CHARS = re.compile(r"[\x00-\x20\x7f\\]")
_HOST_LABEL = re.compile(r"[a-z0-9](?:[a-z0-9-]{0,61}[a-z0-9])?")
_LOCAL_SUFFIXES = ("localhost", "localdomain", "local", "internal", "lan", "home", "home.arpa")
_DENIED_V4 = tuple(ipaddress.ip_network(value) for value in (
    "0.0.0.0/8", "10.0.0.0/8", "100.64.0.0/10", "127.0.0.0/8", "169.254.0.0/16",
    "172.16.0.0/12", "192.0.0.0/24", "192.0.2.0/24", "192.88.99.0/24", "192.168.0.0/16",
    "198.18.0.0/15", "198.51.100.0/24", "203.0.113.0/24", "224.0.0.0/4", "240.0.0.0/4",
    "168.63.129.16/32",  # Azure platform/metadata virtual address, despite its public-looking IP.
))
_GLOBAL_V6 = ipaddress.ip_network("2000::/3")
_DENIED_V6 = tuple(ipaddress.ip_network(value) for value in ("2001::/23", "2002::/16", "3fff::/20"))

_CONTROL = re.compile(r"[\x00-\x08\x0b\x0c\x0e-\x1f\x7f]")
_WHITESPACE = re.compile(r"\s+")

Fetcher = Callable[[str, float, int], "tuple[int, bytes]"]


class RetrievalError(ValueError):
    """A source could not be retrieved or was not eligible for retrieval."""


class SourceTooLarge(RetrievalError):
    """The full source cannot be retained within the evidence limits."""


@dataclass(frozen=True)
class FetchedSource:
    url: str
    status: str
    chars: int = 0
    sha256: str = ""
    fetched_at: str = ""
    text: str = ""
    error: str | None = None

    def as_dict(self, *, include_text: bool = False) -> dict[str, object]:
        data: dict[str, object] = {
            "url": self.url,
            "status": self.status,
            "chars": self.chars,
            "sha256": self.sha256,
            "fetched_at": self.fetched_at,
        }
        if self.error:
            data["error"] = self.error
        if include_text:
            data["text"] = self.text
            data["text_sha256"] = hashlib.sha256(self.text.encode("utf-8")).hexdigest()
        return data


class _Deadline:
    def __init__(self, timeout: float):
        self.end = time.monotonic() + timeout
        self.cancelled = threading.Event()
        self.lock = threading.Lock()
        self.sock: socket.socket | None = None

    def remaining(self) -> float:
        remaining = self.end - time.monotonic()
        if remaining <= 0 or self.cancelled.is_set():
            raise TimeoutError("source retrieval timed out")
        return remaining

    def bind(self, sock: socket.socket) -> None:
        with self.lock:
            self.remaining()
            self.sock = sock

    def unbind(self, sock: socket.socket) -> None:
        with self.lock:
            if self.sock is sock:
                self.sock = None

    def cancel(self) -> None:
        with self.lock:
            self.cancelled.set()
            sock = self.sock
        if sock is not None:
            try:
                sock.shutdown(socket.SHUT_RDWR)
            except OSError:
                pass
            sock.close()


def _bounded_call(operation: Callable[[_Deadline], _T], timeout: float) -> _T:
    # OS DNS and injected fetchers cannot be forcibly interrupted in Python. Daemon
    # workers bound the caller's wait; a semaphore also bounds orphaned workers.
    slots = _FETCH_SLOTS
    if not slots.acquire(blocking=False):
        raise RetrievalError("source retrieval capacity exhausted")
    deadline = _Deadline(timeout)
    future: Future[_T] = Future()

    def run() -> None:
        try:
            deadline.remaining()
            result = operation(deadline)
            deadline.remaining()
            future.set_result(result)
        except BaseException as exc:
            future.set_exception(exc)
        finally:
            slots.release()

    try:
        threading.Thread(target=run, name="source-retrieval", daemon=True).start()
    except Exception:
        slots.release()
        raise
    try:
        result = future.result(timeout=deadline.remaining())
        deadline.remaining()
        return result
    except TimeoutError:
        deadline.cancel()
        raise TimeoutError("source retrieval timed out") from None


def http_fetch(url: str, timeout: float = DEFAULT_TIMEOUT_S, max_bytes: int = DEFAULT_MAX_BYTES) -> tuple[int, bytes]:
    """GET public HTTP(S) with pinned DNS, verified TLS and one total deadline.

    Limits can be tightened, not raised beyond 15 seconds / 512 KiB. Redirects
    are checked independently and never reset the deadline. No proxy is used.
    """
    max_bytes = _byte_limit(max_bytes)
    timeout = _timeout_limit(timeout)
    return _bounded_call(lambda deadline: _http_fetch(url, deadline, max_bytes), timeout)


def _http_fetch(url: str, deadline: _Deadline, max_bytes: int) -> tuple[int, bytes]:
    for hop in range(MAX_REDIRECTS + 1):
        deadline.remaining()
        target = _parse_target(url)
        family, address = _resolve_public(target)
        connection = http.client.HTTPConnection(target.host, target.port, timeout=deadline.remaining())
        sock = socket.socket(family, socket.SOCK_STREAM, socket.IPPROTO_TCP)
        try:
            deadline.bind(sock)
            sock.settimeout(deadline.remaining())
            sock.connect(address)
            if target.scheme == "https":
                context = ssl.create_default_context()
                sock = context.wrap_socket(sock, server_hostname=target.host, do_handshake_on_connect=False)
                deadline.bind(sock)
                sock.settimeout(deadline.remaining())
                sock.do_handshake()
            connection.sock = sock
            sock.settimeout(deadline.remaining())
            connection.request("GET", target.path, headers={
                "Host": target.authority,
                "User-Agent": "shorts-factory/0.1 (+source verification)",
                "Accept": "text/html,text/plain;q=0.9,*/*;q=0.1",
                "Accept-Encoding": "identity",
                "Connection": "close",
            })
            sock.settimeout(deadline.remaining())
            with connection.getresponse() as response:
                deadline.remaining()
                location = response.getheader("Location")
                if response.status in _REDIRECT_STATUSES and location:
                    if hop >= MAX_REDIRECTS:
                        raise RetrievalError("source exceeded the redirect limit")
                    if len(location) > MAX_URL_CHARS or _INVALID_URL_CHARS.search(location):
                        raise RetrievalError("invalid source redirect")
                    url = urljoin(url, location)
                    continue
                return response.status, _read_body(response, max_bytes, deadline, sock)
        finally:
            connection.close()
            sock.close()
            deadline.unbind(sock)
    raise RetrievalError("source exceeded the redirect limit")


def _byte_limit(max_bytes: int) -> int:
    if type(max_bytes) is not int or max_bytes <= 0:
        raise RetrievalError("source byte limit must be a positive integer")
    return min(max_bytes, DEFAULT_MAX_BYTES)


def _timeout_limit(timeout: float) -> float:
    if type(timeout) not in {int, float} or not math.isfinite(timeout) or timeout <= 0:
        raise RetrievalError("source timeout must be positive and finite")
    return min(timeout, DEFAULT_TIMEOUT_S)


def _read_body(response: http.client.HTTPResponse, max_bytes: int, deadline: _Deadline,
               sock: socket.socket) -> bytes:
    length = response.getheader("Content-Length")
    if length is not None:
        if not re.fullmatch(r"[0-9]+", length) or len(length) > 20:
            raise RetrievalError("invalid source content length")
        if int(length) > max_bytes:
            raise SourceTooLarge("source exceeded the byte limit")
    if response.getheader("Content-Range") and response.status != 206:
        raise RetrievalError("partial source is not complete evidence")
    if response.getheader("Content-Encoding", "identity").lower().strip() != "identity":
        raise RetrievalError("encoded source is not plain evidence")
    body = bytearray()
    while True:
        if response.isclosed():
            # http.client closes the connection itself once the last byte (or the
            # final chunk) arrives. Touching the socket after that raises
            # WinError 10038 on Windows, which turned every live fetch into an
            # error and left source verification with zero readable evidence.
            break
        sock.settimeout(deadline.remaining())
        chunk = response.read1(min(64 * 1024, max_bytes + 1 - len(body)))
        deadline.remaining()
        if not chunk:
            break
        body.extend(chunk)
        if len(body) > max_bytes:
            raise SourceTooLarge("source exceeded the byte limit")
    if response.length not in {None, 0}:
        raise RetrievalError("incomplete source body")
    return bytes(body)


@dataclass(frozen=True)
class _Target:
    scheme: str
    host: str
    port: int
    authority: str
    path: str


def _public_ip(host: str) -> bool:
    address = ipaddress.ip_address(host)
    if not address.is_global or address.is_multicast or address.is_reserved:
        return False
    if isinstance(address, ipaddress.IPv4Address):
        return not any(address in network for network in _DENIED_V4)
    # Exclude IPv4-mapped, NAT64, transition/tunnel and special-use IPv6 ranges,
    # including ranges Python 3.11/3.12 classified less strictly than newer releases.
    return address in _GLOBAL_V6 and not any(address in network for network in _DENIED_V6)


def _parse_target(url: str) -> _Target:
    if not isinstance(url, str) or len(url) > MAX_URL_CHARS or _INVALID_URL_CHARS.search(url):
        raise RetrievalError("invalid source URL")
    try:
        parts = urlsplit(url)
        if parts.scheme not in {"http", "https"} or not parts.hostname or parts.username is not None:
            raise ValueError
        authority_pattern = r"\[[^\]]+\](?::[0-9]+)?" if parts.netloc.startswith("[") else r"[^:]+(?::[0-9]+)?"
        if not re.fullmatch(authority_pattern, parts.netloc):
            raise ValueError
        default_port = 443 if parts.scheme == "https" else 80
        port = parts.port if parts.port is not None else default_port
        if port != default_port:
            raise ValueError
        host = parts.hostname.encode("idna").decode("ascii").lower().removesuffix(".")
        if "%" in host:
            raise ValueError
        try:
            ipaddress.ip_address(host)
        except ValueError:
            labels = host.split(".")
            if len(host) > 253 or len(labels) < 2 or not all(_HOST_LABEL.fullmatch(label) for label in labels):
                raise ValueError
            if all(re.fullmatch(r"(?:0x[0-9a-f]+|[0-9]+)", label) for label in labels):
                raise ValueError
            if any(host == suffix or host.endswith("." + suffix) for suffix in _LOCAL_SUFFIXES):
                raise ValueError
            if host == "metadata.google":
                raise ValueError
        else:
            if not _public_ip(host):
                raise ValueError
        authority = f"[{host}]" if ":" in host else host
        if parts.port is not None:
            authority += f":{port}"
        path = quote(parts.path or "/", safe="/%:@!$&'()*+,;=-._~")
        if parts.query:
            path += "?" + quote(parts.query, safe="/?%:@!$&'()*+,;=-._~")
        return _Target(parts.scheme, host, port, authority, path)
    except (ValueError, UnicodeError):
        raise RetrievalError("source URL is not eligible for public HTTP(S) retrieval") from None


def eligible_url(url: str) -> bool:
    """Check URL syntax/local literals without DNS; the transport validates and pins DNS."""
    try:
        _parse_target(url)
    except RetrievalError:
        return False
    return True


def _recorded_url(url: str) -> str:
    try:
        if urlsplit(url).username is not None:
            return "<redacted URL>"
    except ValueError:
        return "<invalid URL>"
    return url


def _resolve_public(target: _Target) -> tuple[int, tuple]:
    try:
        address = ipaddress.ip_address(target.host)
    except ValueError:
        answers = socket.getaddrinfo(target.host, target.port, socket.AF_UNSPEC,
                                     socket.SOCK_STREAM, socket.IPPROTO_TCP)
    else:
        family = socket.AF_INET6 if address.version == 6 else socket.AF_INET
        sockaddr = (str(address), target.port, 0, 0) if address.version == 6 else (str(address), target.port)
        answers = [(family, socket.SOCK_STREAM, socket.IPPROTO_TCP, "", sockaddr)]
    validated = []
    for family, kind, protocol, _, sockaddr in answers:
        if family not in {socket.AF_INET, socket.AF_INET6} or kind != socket.SOCK_STREAM:
            raise RetrievalError("unsupported DNS address")
        address = ipaddress.ip_address(sockaddr[0])
        if (protocol not in {0, socket.IPPROTO_TCP} or sockaddr[1] != target.port or "%" in sockaddr[0]
                or (address.version == 6) != (family == socket.AF_INET6) or not _public_ip(str(address))):
            raise RetrievalError("DNS answer is not a public address")
        if family == socket.AF_INET6 and (len(sockaddr) != 4 or sockaddr[2:] != (0, 0)):
            raise RetrievalError("scoped DNS addresses are not eligible")
        numeric = (str(address), target.port, 0, 0) if address.version == 6 else (str(address), target.port)
        validated.append((family, numeric))
    if not validated:
        raise RetrievalError("DNS returned no public addresses")
    return validated[0]


class _EvidenceHTMLParser(HTMLParser):
    def __init__(self):
        super().__init__(convert_charrefs=False)
        self.chunks: list[str] = []
        self.hidden: str | None = None

    def handle_starttag(self, tag: str, attrs: list) -> None:
        self.chunks.append(" ")
        if tag in {"script", "style"}:
            self.hidden = tag

    def handle_endtag(self, tag: str) -> None:
        self.chunks.append(" ")
        if tag == self.hidden:
            self.hidden = None

    def handle_data(self, data: str) -> None:
        if self.hidden is None:
            self.chunks.append(data)

    def handle_entityref(self, name: str) -> None:
        self.handle_data(f"&{name};")

    def handle_charref(self, name: str) -> None:
        self.handle_data(f"&#{name};")


def clean_text(body: bytes) -> str:
    """Decode to plain, single-spaced text. Markup is evidence noise, not content."""
    if not isinstance(body, bytes):
        raise RetrievalError("source body must be bytes")
    if len(body) > DEFAULT_MAX_BYTES:
        raise SourceTooLarge("source exceeded the byte limit")
    parser = _EvidenceHTMLParser()
    parser.feed(body.decode("utf-8", errors="replace"))
    parser.close()
    raw = "".join(parser.chunks)
    raw = _CONTROL.sub(" ", raw)
    text = _WHITESPACE.sub(" ", raw).strip()
    if len(text) > MAX_TEXT_CHARS:
        raise SourceTooLarge("source exceeded the text limit")
    return text


def fetch_sources(
    urls: list[str],
    *,
    fetcher: Fetcher | None = None,
    max_bytes: int = DEFAULT_MAX_BYTES,
    timeout: float = DEFAULT_TIMEOUT_S,
    max_sources: int = DEFAULT_MAX_SOURCES,
) -> list[FetchedSource]:
    """Retrieve up to ``max_sources`` distinct http(s) URLs, recording failures honestly."""
    max_bytes = _byte_limit(max_bytes)
    timeout = _timeout_limit(timeout)
    results: list[FetchedSource] = []
    seen: set[str] = set()
    for url in urls:
        if len(results) >= max_sources:
            break
        if not url or url in seen:
            continue
        seen.add(url)
        if not eligible_url(url):
            results.append(FetchedSource(url=_recorded_url(url), status="skipped",
                                          error="source URL is not eligible for public HTTP(S) retrieval"))
            continue
        try:
            status, text, digest = _bounded_call(
                lambda deadline, url=url: _fetch_evidence(url, fetcher, max_bytes, deadline), timeout,
            )
        except Exception as exc:  # network failure must not kill the job; it must be recorded
            results.append(FetchedSource(url=url, status="error", error=type(exc).__name__))
            continue
        results.append(
            FetchedSource(
                url=url,
                status="ok" if 200 <= status < 300 and status != 206 else f"http_{status}",
                chars=len(text),
                sha256=digest,
                fetched_at=timestamp(),
                text=text,
            )
        )
    return results


def _fetch_evidence(url: str, fetcher: Fetcher | None, max_bytes: int,
                    deadline: _Deadline) -> tuple[int, str, str]:
    status, body = (_http_fetch(url, deadline, max_bytes) if fetcher is None
                    else fetcher(url, deadline.remaining(), max_bytes))
    deadline.remaining()
    if type(status) is not int or not 100 <= status <= 599 or not isinstance(body, bytes):
        raise RetrievalError("invalid source fetcher result")
    if len(body) > max_bytes:
        raise SourceTooLarge("source exceeded the byte limit")
    text = clean_text(body)
    return status, text, hashlib.sha256(body).hexdigest()


def retrieve_or_raise(urls: list[str], **kwargs: object) -> list[FetchedSource]:
    """Fetch sources and fail loudly when none could be read.

    Used by the pipeline for factual scripts: a factual script whose sources
    cannot be read cannot be verified, so it must not quietly pass as verified.
    """
    sources = fetch_sources(urls, **kwargs)
    if any(source.status == "ok" and source.text for source in sources):
        return sources
    raise RetrievalError(
        "no source could be retrieved for verification: "
        + "; ".join(f"{source.url} -> {source.status}" for source in sources or [])
    )


def timestamp() -> str:
    return time.strftime("%Y-%m-%dT%H:%M:%SZ", time.gmtime())
