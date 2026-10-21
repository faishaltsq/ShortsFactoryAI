"""ASGI entrypoint for uvicorn: `uv run uvicorn apps.api.server:app --port 8018`.

Kept separate from ``create_app`` so importing ``apps.api.main`` never opens a
database as a side effect (tests construct their own store-backed app).
"""

from apps.api.main import create_app

app = create_app()
