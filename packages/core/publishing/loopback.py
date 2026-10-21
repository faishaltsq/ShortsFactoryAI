"""Bounded installed-app loopback listener; OAuth callback secrets are never logged."""
from __future__ import annotations

import time
from http.server import BaseHTTPRequestHandler, HTTPServer
from typing import Any, Callable

from .errors import PublishingError
from .oauth import OAuthFlow


class _BoundedServer(HTTPServer):
    def get_request(self):
        connection, address = super().get_request()
        connection.settimeout(1.0)
        return connection, address

    def handle_error(self, request, client_address):
        # BaseServer prints a traceback (and potentially a callback) to stderr.
        return


def run_loopback(flow: OAuthFlow, *, allow_connect: bool, browser_open: Callable[[str], bool],
                 timeout_s: float = 120, server_factory: Callable[..., Any] = _BoundedServer,
                 monotonic: Callable[[], float] = time.monotonic) -> None:
    if allow_connect is not True:
        raise PublishingError("connect_permission_required")
    if not 0 < timeout_s <= 120:
        raise ValueError("invalid_callback_timeout")
    callback: list[str] = []
    origin: list[str] = []

    class Handler(BaseHTTPRequestHandler):
        def log_message(self, format, *args):
            return

        def do_GET(self):
            valid = (self.headers.get("Host") == origin[0] and len(self.path) <= 8192
                     and self.path.partition("?")[0] == "/oauth2/callback")
            self.send_response(200 if valid else 400)
            self.send_header("Content-Type", "text/plain; charset=utf-8")
            self.send_header("Cache-Control", "no-store")
            self.send_header("Connection", "close")
            self.end_headers()
            if valid:
                callback.append("http://" + origin[0] + self.path)
            self.wfile.write(b"Return to the operator terminal.")

    server = server_factory(("127.0.0.1", 0), Handler)
    try:
        origin.append(f"127.0.0.1:{server.server_address[1]}")
        auth = flow.begin("http://" + origin[0] + "/oauth2/callback", allow_connect=True)
        deadline = monotonic() + timeout_s
        try:
            opened = browser_open(auth.authorization_url)
        except Exception:
            raise PublishingError("oauth_browser_open_failed") from None
        if opened is not True:
            raise PublishingError("oauth_browser_open_failed")
        while not callback:
            remaining = deadline - monotonic()
            if remaining <= 0:
                raise PublishingError("oauth_callback_timeout")
            server.timeout = min(0.5, remaining)
            server.handle_request()
        if monotonic() >= deadline:
            raise PublishingError("oauth_callback_timeout")
        flow.complete(auth, callback[0], allow_connect=True)
    finally:
        server.server_close()
