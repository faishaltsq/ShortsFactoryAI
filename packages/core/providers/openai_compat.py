"""OpenAI-compatible chat completions adapter (DeepSeek or any compatible endpoint)."""

from __future__ import annotations

import json
import time
from typing import Any

import httpx

from .base import ProviderError, ProviderResult, Tier


class OpenAICompatProvider:
    def __init__(
        self,
        *,
        name: str,
        base_url: str,
        api_key: str,
        model: str,
        tier: Tier = "worker",
        timeout_s: int = 120,
        max_retries: int = 3,
        temperature: float = 0.7,
    ) -> None:
        self.name = name
        self.tier = tier
        self.base_url = base_url.rstrip("/")
        self._api_key = api_key
        self.model = model
        self.timeout_s = timeout_s
        self.max_retries = max_retries
        self.temperature = temperature

    @property
    def _endpoint(self) -> str:
        return f"{self.base_url}/chat/completions"

    def _headers(self) -> dict[str, str]:
        headers = {"Content-Type": "application/json"}
        if self._api_key:
            headers["Authorization"] = f"Bearer {self._api_key}"
        return headers

    def healthy(self) -> bool:
        if not self.base_url:
            return False
        try:
            resp = httpx.get(f"{self.base_url}/models", headers=self._headers(), timeout=8.0)
            if resp.status_code != 200:
                return False
            data = resp.json()
            return any(item.get("id") == self.model for item in data.get("data", []))
        except (httpx.HTTPError, ValueError, TypeError):
            return False

    def complete(self, *, task: str, system: str, user: str) -> ProviderResult:
        payload: dict[str, Any] = {
            "model": self.model,
            "temperature": self.temperature,
            "messages": [
                {"role": "system", "content": system},
                {"role": "user", "content": user},
            ],
        }
        last_error = ""
        started = time.perf_counter()
        for attempt in range(1, self.max_retries + 1):
            try:
                resp = httpx.post(
                    self._endpoint,
                    headers=self._headers(),
                    json=payload,
                    timeout=float(self.timeout_s),
                )
            except httpx.HTTPError as exc:
                last_error = f"transport error: {type(exc).__name__}"
                if attempt < self.max_retries:
                    time.sleep(min(2**attempt, 15))
                    continue
                raise ProviderError(last_error, provider=self.name, retryable=True) from exc

            if resp.status_code >= 500 or resp.status_code == 429:
                last_error = f"HTTP {resp.status_code} from {self.name}"
                if attempt < self.max_retries:
                    time.sleep(min(2**attempt, 15))
                    continue
                raise ProviderError(last_error, provider=self.name, retryable=True)

            if resp.status_code >= 400:
                raise ProviderError(
                    f"HTTP {resp.status_code} from {self.name}",
                    provider=self.name,
                    retryable=False,
                )

            body = resp.text
            try:
                # Some gateways append SSE trailers ("data: [DONE]") after the
                # JSON body. raw_decode takes the first object and ignores them.
                data, _ = json.JSONDecoder().raw_decode(body.lstrip())
            except json.JSONDecodeError as exc:
                raise ProviderError(
                    f"non-JSON body from {self.name}", provider=self.name
                ) from exc
            try:
                content = data["choices"][0]["message"]["content"] or ""
            except (KeyError, IndexError, TypeError) as exc:
                raise ProviderError("malformed completion response", provider=self.name) from exc

            usage = data.get("usage") or {}
            elapsed_ms = int((time.perf_counter() - started) * 1000)
            return ProviderResult(
                content=content,
                provider=self.name,
                model=data.get("model", self.model),
                prompt_tokens=int(usage.get("prompt_tokens", 0) or 0),
                completion_tokens=int(usage.get("completion_tokens", 0) or 0),
                elapsed_ms=elapsed_ms,
                raw={"task": task, "status_code": resp.status_code},
            )

        raise ProviderError(last_error or "exhausted retries", provider=self.name, retryable=True)
