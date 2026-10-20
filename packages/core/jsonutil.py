"""Extract JSON payloads from LLM text. Models wrap JSON in prose or fences."""

from __future__ import annotations

import json
import re
from typing import Any

_FENCE = re.compile(r"```(?:json)?\s*(.*?)```", re.DOTALL | re.IGNORECASE)


def extract_json(text: str) -> Any:
    """Return the first parseable JSON object/array found in *text*."""
    if not text or not text.strip():
        raise ValueError("empty model output")

    stripped = text.strip()
    try:
        return json.loads(stripped)
    except json.JSONDecodeError:
        pass

    for match in _FENCE.finditer(text):
        candidate = match.group(1).strip()
        try:
            return json.loads(candidate)
        except json.JSONDecodeError:
            continue

    # Balanced-brace scan from each opening brace.
    openers = "{["
    closers = {"}": "{", "]": "["}
    for i, ch in enumerate(stripped):
        if ch not in openers:
            continue
        depth = 0
        in_str = False
        escape = False
        for j in range(i, len(stripped)):
            c = stripped[j]
            if in_str:
                if escape:
                    escape = False
                elif c == "\\":
                    escape = True
                elif c == '"':
                    in_str = False
                continue
            if c == '"':
                in_str = True
            elif c in openers:
                depth += 1
            elif c in closers:
                depth -= 1
                if depth == 0:
                    try:
                        return json.loads(stripped[i : j + 1])
                    except json.JSONDecodeError:
                        break
    raise ValueError(f"no JSON found in model output: {stripped[:200]!r}")


def extract_model(text: str, model_cls: type, *, wrap_key: str | None = None) -> Any:
    """Parse JSON and validate into a pydantic model (or plain dict/list).

    `wrap_key` tolerates a model that answers with a bare array where the
    contract expects an object: the array is wrapped as {wrap_key: [...]}.
    """
    data = extract_json(text)
    validator = getattr(model_cls, "model_validate", None)
    if validator is None:
        if model_cls in (dict, list, tuple, set) and not isinstance(data, model_cls):
            if model_cls is dict and isinstance(data, list) and wrap_key:
                data = {wrap_key: data}
            else:
                raise ValueError(f"expected {model_cls.__name__}, got {type(data).__name__}")
        return data
    try:
        return validator(data)
    except Exception as exc:
        raise ValueError(f"{model_cls.__name__} validation failed: {exc}") from exc
