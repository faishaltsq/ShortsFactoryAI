"""Fan out real pipeline boundaries to both Studio event feeds."""
from __future__ import annotations

from ..activity import ActivityReporter
from .lifecycle import RunObserver


class RunTelemetry:
    def __init__(self, store, job_id: str, *, source: str, activity_token: str) -> None:
        self.events = RunObserver(store, job_id, source=source)
        self.activity = ActivityReporter(store, job_id, activity_token)

    def start(self) -> None:
        self.events.start()
        self.activity.begin("FactoryOrchestrator", "PREFLIGHT")

    def stage(self, agent: str, stage: str, *, reused: bool) -> None:
        if not reused:
            self.events.started(stage)
        self.activity.begin(agent, stage, reused=reused)

    def done(self, agent: str, stage: str, artifact: str, *, reused: bool) -> None:
        self.events.completed(stage, reused=reused)
        self.activity.complete(agent, artifact)

    def failed(self, *, error_type: str, blocked: bool = False) -> None:
        self.events.failed(blocked=blocked, error_type=error_type)
        self.activity.finish("blocked" if blocked else "failed")

    def render_progress(self, progress) -> None:
        self.events.render_progress(progress)

    def finish(self, state: str, outcome: str) -> None:
        self.events.finish(state)
        self.activity.finish(outcome)
