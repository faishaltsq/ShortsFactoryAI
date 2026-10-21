"""Google installed-app authorization with S256 PKCE and one-use loopback state."""
from __future__ import annotations

import base64
import hashlib
import math
import secrets
import time
from dataclasses import dataclass, field
from typing import Any, Callable
from urllib.parse import parse_qs, urlencode, urlsplit

import httpx

from .errors import PublishingError
from .secure import ProtectedStore
from .transport import SafeHTTP, safe_json

AUTHORIZATION_ENDPOINT = "https://accounts.google.com/o/oauth2/v2/auth"
TOKEN_ENDPOINT = "https://oauth2.googleapis.com/token"
# videos.update does not accept youtube.upload; this is the common documented scope.
YOUTUBE_SCOPE = "https://www.googleapis.com/auth/youtube.force-ssl"


def _secret_string(value: Any) -> bool:
    return isinstance(value, str) and 0 < len(value) <= 8192 and not any(c.isspace() for c in value)


@dataclass(frozen=True)
class InstalledClient:
    client_id: str = field(repr=False)
    client_secret: str = field(default="", repr=False)

    @classmethod
    def from_data(cls, data: dict[str, Any]) -> InstalledClient:
        installed = data.get("installed")
        if not isinstance(installed, dict) or not _secret_string(installed.get("client_id")):
            raise PublishingError("installed_client_required")
        if installed.get("auth_uri", AUTHORIZATION_ENDPOINT) != AUTHORIZATION_ENDPOINT:
            raise PublishingError("installed_client_endpoint_invalid")
        if installed.get("token_uri", TOKEN_ENDPOINT) != TOKEN_ENDPOINT:
            raise PublishingError("installed_client_endpoint_invalid")
        secret = installed.get("client_secret", "")
        if secret and not _secret_string(secret):
            raise PublishingError("installed_client_invalid")
        return cls(installed["client_id"], secret)

    @classmethod
    def from_store(cls, store: ProtectedStore) -> InstalledClient:
        data = store.read("client")
        if data is None:
            raise PublishingError("installed_client_not_configured")
        return cls.from_data(data)

    def form(self) -> dict[str, str]:
        values = {"client_id": self.client_id}
        if self.client_secret:
            values["client_secret"] = self.client_secret
        return values


def _challenge(verifier: str) -> str:
    return base64.urlsafe_b64encode(hashlib.sha256(verifier.encode("ascii")).digest()).rstrip(b"=").decode("ascii")


@dataclass(frozen=True)
class AuthorizationRequest:
    authorization_url: str = field(repr=False)
    redirect_uri: str
    state: str = field(repr=False)
    verifier: str = field(repr=False)
    challenge: str = field(repr=False)
    expires_at: float


class OAuthFlow:
    def __init__(self, client: InstalledClient, store: ProtectedStore, http: httpx.Client, *,
                 clock: Callable[[], float] = time.time, sleep: Callable[[float], None] = time.sleep,
                 max_attempts: int = 3, timeout_s: float = 20) -> None:
        self.client, self.store, self.clock = client, store, clock
        self.transport = SafeHTTP(http, max_attempts=max_attempts, timeout_s=timeout_s, sleep=sleep)
        self._pending: dict[str, AuthorizationRequest] = {}

    def begin(self, redirect_uri: str, *, allow_connect: bool) -> AuthorizationRequest:
        if allow_connect is not True:
            raise PublishingError("connect_permission_required")
        try:
            uri = urlsplit(redirect_uri)
            valid = (uri.scheme == "http" and uri.hostname == "127.0.0.1" and uri.port
                     and not uri.username and not uri.password and not uri.query and not uri.fragment
                     and uri.path == "/oauth2/callback")
        except ValueError:
            valid = False
        if not valid:
            raise PublishingError("loopback_redirect_required")
        self._pending.clear()
        verifier, state = secrets.token_urlsafe(64), secrets.token_urlsafe(32)
        challenge = _challenge(verifier)
        params = {"client_id": self.client.client_id, "redirect_uri": redirect_uri, "response_type": "code",
                  "scope": YOUTUBE_SCOPE, "state": state, "code_challenge": challenge,
                  "code_challenge_method": "S256", "access_type": "offline", "prompt": "consent"}
        request = AuthorizationRequest(AUTHORIZATION_ENDPOINT + "?" + urlencode(params), redirect_uri,
                                       state, verifier, challenge, self.clock() + 120)
        self._pending[state] = request
        return request

    def complete(self, auth: AuthorizationRequest, callback_url: str, *, allow_connect: bool) -> None:
        if allow_connect is not True:
            raise PublishingError("connect_permission_required")
        original = self._pending.pop(auth.state, None)
        if original is None or original != auth or self.clock() >= auth.expires_at:
            raise PublishingError("oauth_request_expired_or_invalid")
        if not secrets.compare_digest(_challenge(auth.verifier), auth.challenge):
            raise PublishingError("oauth_pkce_mismatch")
        callback, expected = urlsplit(callback_url), urlsplit(auth.redirect_uri)
        if (callback.scheme, callback.netloc, callback.path) != (expected.scheme, expected.netloc, expected.path) or callback.fragment:
            raise PublishingError("oauth_callback_invalid")
        try:
            query = parse_qs(callback.query, keep_blank_values=True, max_num_fields=10)
        except ValueError:
            raise PublishingError("oauth_callback_invalid") from None
        states, codes = query.get("state", []), query.get("code", [])
        if len(states) != 1 or not secrets.compare_digest(states[0].encode("utf-8"), auth.state.encode("ascii")):
            raise PublishingError("oauth_state_mismatch")
        if "error" in query or len(codes) != 1 or not _secret_string(codes[0]):
            raise PublishingError("oauth_authorization_rejected")
        form = {**self.client.form(), "grant_type": "authorization_code", "code": codes[0],
                "redirect_uri": auth.redirect_uri, "code_verifier": auth.verifier}
        # Authorization codes are one-use. A lost exchange response requires --connect again.
        with self.store.locked("tokens"):
            response = self.transport.request("POST", TOKEN_ENDPOINT, retry_safe=False, accepted=(200,), data=form)
            token = _token_data(safe_json(response), self.clock(), old_refresh=None)
            self.store.write("tokens", token)


class TokenManager:
    def __init__(self, client: InstalledClient, store: ProtectedStore, http: httpx.Client, *,
                 clock: Callable[[], float] = time.time, sleep: Callable[[float], None] = time.sleep,
                 max_attempts: int = 3, timeout_s: float = 20) -> None:
        self.client, self.store, self.clock = client, store, clock
        self.transport = SafeHTTP(http, max_attempts=max_attempts, timeout_s=timeout_s, sleep=sleep)

    def access_token(self, *, allow_refresh: bool) -> str:
        with self.store.locked("tokens"):
            token = self.store.read("tokens")
            if token is None:
                raise PublishingError("oauth_not_connected")
            expiry = token.get("expires_at", 0)
            valid_expiry = isinstance(expiry, (int, float)) and math.isfinite(expiry)
            if valid_expiry and expiry > self.clock() + 60 and _secret_string(token.get("access_token")):
                return token["access_token"]
            if allow_refresh is not True:
                raise PublishingError("oauth_token_expired")
            refresh = token.get("refresh_token")
            if not _secret_string(refresh):
                raise PublishingError("oauth_reconnect_required")
            response = self.transport.request("POST", TOKEN_ENDPOINT, retry_safe=True, accepted=(200,),
                                              data={**self.client.form(), "grant_type": "refresh_token",
                                                    "refresh_token": refresh})
            updated = _token_data(safe_json(response), self.clock(), old_refresh=refresh)
            self.store.write("tokens", updated)
            return updated["access_token"]


def _token_data(data: dict[str, Any], now: float, *, old_refresh: str | None) -> dict[str, Any]:
    expires = data.get("expires_in")
    refresh = data.get("refresh_token", old_refresh)
    token_type = data.get("token_type")
    if (not _secret_string(data.get("access_token")) or not _secret_string(refresh)
            or not isinstance(token_type, str) or token_type.lower() != "bearer"
            or not isinstance(expires, (int, float)) or isinstance(expires, bool)
            or not math.isfinite(expires) or not 0 < expires <= 86400):
        raise PublishingError("oauth_token_response_invalid")
    scope = data.get("scope")
    if scope is not None and (not isinstance(scope, str) or YOUTUBE_SCOPE not in scope.split()):
        raise PublishingError("oauth_scope_missing")
    return {"access_token": data["access_token"], "refresh_token": refresh,
            "expires_at": now + expires, "scope": YOUTUBE_SCOPE, "token_type": "Bearer"}
