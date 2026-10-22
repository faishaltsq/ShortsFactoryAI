import { describe, expect, it } from "vitest";

import type { JobDetail } from "./api";
import { agentStatus, roster } from "./team";

const detail = (running = true, token = "a".repeat(32)): JobDetail => ({
  record: {
    id: "a".repeat(16),
    title: "Test",
    state: "TOPIC_SELECTED",
    attempts: 0,
    created_at: "2026-01-01",
    updated_at: "2026-01-01",
    last_error: null,
    payload: {
      studio_activity: {
        token: "a".repeat(32),
        agent: "ScriptAgent",
        stage: "SCRIPT_GENERATED",
        phase: "running",
        updated_at: "2026-01-01",
        completed: { ResearchAgent: "research.json" },
      },
    },
  },
  events: [],
  artifacts: [],
  run: { running, activity_token: token },
});

describe("truthful team status", () => {
  it("requires a matching live token, never a lifecycle-state guess", () => {
    expect(agentStatus("ScriptAgent", detail(), false).kind).toBe("working");
    expect(agentStatus("ScriptAgent", detail(false), false).kind).toBe("unknown");
    expect(agentStatus("ScriptAgent", detail(true, "b".repeat(32)), false).kind).toBe("unknown");
    expect(agentStatus("ScriptAgent", detail(), true).kind).toBe("unknown");
    expect(agentStatus("ResearchAgent", detail(), false).kind).toBe("done");
    expect(agentStatus("FactoryOrchestrator", detail(), false).kind).toBe("working");
  });

  it("handles legacy payloads, unsupported roles and old API metadata", () => {
    const old = detail();
    old.record.payload = {};
    expect(agentStatus("ScriptAgent", old, false).kind).toBe("unknown");
    expect(agentStatus("PublishAgent", detail(), false, false).kind).toBe("unavailable");
    expect(roster(null)).toEqual([]);
    old.record.payload.studio_activity = {
      token: "a".repeat(32),
      agent: "ScriptAgent",
      phase: "invented",
    };
    expect(agentStatus("FactoryOrchestrator", old, false).kind).toBe("unknown");
  });

  it("distinguishes failed, blocked, validating and completed runs", () => {
    for (const [phase, kind] of [
      ["failed", "failed"],
      ["blocked", "blocked"],
      ["validating", "validating"],
      ["done", "idle"],
    ] as const) {
      const value = detail();
      value.record.payload.studio_activity = {
        token: "a".repeat(32),
        agent: "ScriptAgent",
        phase,
        completed: {},
      };
      expect(agentStatus("ScriptAgent", value, false).kind).toBe(kind);
    }
  });
});
