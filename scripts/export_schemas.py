#!/usr/bin/env python3
"""Export or verify JSON Schemas from the canonical Pydantic artifact contracts."""
from __future__ import annotations

import argparse
import json
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))

from jsonschema import Draft202012Validator  # noqa: E402
from packages.core.artifacts import ARTIFACT_MODELS  # noqa: E402


def main() -> int:
    parser = argparse.ArgumentParser()
    parser.add_argument("--check", action="store_true")
    args = parser.parse_args()
    directory = ROOT / "config" / "schemas"
    directory.mkdir(parents=True, exist_ok=True)
    failures = []
    for name, model in ARTIFACT_MODELS.items():
        schema = {"$schema": "https://json-schema.org/draft/2020-12/schema", **model.model_json_schema(by_alias=True)}
        Draft202012Validator.check_schema(schema)
        path = directory / name
        if args.check:
            if not path.is_file() or json.loads(path.read_text(encoding="utf-8")) != schema:
                failures.append(name)
        else:
            path.write_text(json.dumps(schema, indent=2, ensure_ascii=False) + "\n", encoding="utf-8")
    if failures:
        print("stale or missing schemas: " + ", ".join(failures))
        return 1
    print(f"{len(ARTIFACT_MODELS)} artifact schemas {'verified' if args.check else 'exported'}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
