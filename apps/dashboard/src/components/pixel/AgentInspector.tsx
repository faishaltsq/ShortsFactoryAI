import type { CSSProperties } from "react";

import { FieldRow, PromptEditor } from "@/components/studio";
import type { AgentStatus, Member } from "@/lib/team";
import type { useStudio } from "@/lib/useStudio";
import { PixelAvatar } from "./PixelAvatar";

/**
 * The persona card. Every role is inspectable; only roles whose system prompt
 * the operator actually owns get model controls.
 *
 * The persona is presentation only. Behaviour still comes from the system
 * prompt, which is why the editable branch says so explicitly.
 */
export function AgentInspector({
  member,
  state,
  studio,
  models,
  modelsError,
}: {
  member: Member;
  state: AgentStatus;
  studio: ReturnType<typeof useStudio>;
  models: string[];
  modelsError: string | null;
}) {
  const current = studio.draft.agents[member.id] ?? {};
  return (
    <section
      className="px-frame px-inspector"
      id="agent-inspector"
      aria-label={`Profil ${member.persona}`}
      style={{ "--agent-accent": member.accent } as CSSProperties}
    >
      <header>
        <PixelAvatar member={member} kind={state.kind} size={112} />
        <div>
          <p className="px-eyebrow">KARTU ANGGOTA</p>
          <h2>{member.persona}</h2>
          <p>{member.role}</p>
          <code>{member.id}</code>
        </div>
      </header>
      <p>{member.description}</p>
      <p className="mt-3 text-zinc-400">
        {member.personality ?? "Profil karakter belum tersedia dari API ini."}
      </p>
      {member.motto && (
        <blockquote>
          <span className="px-eyebrow">Motto</span>
          <p>“{member.motto}”</p>
        </blockquote>
      )}
      <dl>
        <dt>Status</dt>
        <dd>
          <span className="px-status" data-kind={state.kind}>
            {state.label}
          </span>
        </dd>
        <dt>Tier</dt>
        <dd>{member.tier}</dd>
        <dt>Stage</dt>
        <dd>{member.stage}</dd>
      </dl>
      {!member.available ? (
        <p className="mt-4">Belum tersedia. Publikasi tetap memerlukan persetujuan operator.</p>
      ) : !member.editable ? (
        <p className="mt-4">Dikelola sistem; tidak memakai override model.</p>
      ) : (
        <div className="px-agent-fields">
          <p className="text-xs text-zinc-400">
            Persona hanya identitas tampilan. Perilaku model mengikuti system prompt di bawah.
          </p>
          <FieldRow
            label="Model"
            hint={modelsError ? `Daftar model tidak tersedia: ${modelsError}` : "Kosong = default provider"}
            error={studio.errorFor(member.id, "model")}
          >
            <input
              list={`models-${member.id}`}
              value={current.model ?? ""}
              onChange={(e) => studio.patchAgent(member.id, "model", e.target.value || null)}
              placeholder="ikuti default provider"
              className="w-full rounded-md border border-zinc-700 bg-zinc-900 px-3 py-2"
            />
            <datalist id={`models-${member.id}`}>
              {models.map((m) => (
                <option key={m} value={m} />
              ))}
            </datalist>
          </FieldRow>
          <FieldRow
            label="Temperature (0–2)"
            hint="Kosong = temperature provider"
            error={studio.errorFor(member.id, "temperature")}
          >
            <input
              type="number"
              min={0}
              max={2}
              step={0.1}
              value={current.temperature ?? ""}
              placeholder="0.7"
              onChange={(e) =>
                studio.patchAgent(
                  member.id,
                  "temperature",
                  e.target.value === "" ? null : Number(e.target.value),
                )
              }
              className="w-full rounded-md border border-zinc-700 bg-zinc-900 px-3 py-2"
            />
          </FieldRow>
          <PromptEditor
            value={current.prompt ?? ""}
            defaultValue={studio.meta?.default_prompts[member.id] ?? ""}
            onChange={(text) => studio.patchAgent(member.id, "prompt", text || null)}
            onReset={() => studio.resetAgentPrompt(member.id)}
            error={studio.errorFor(member.id, "prompt")}
          />
        </div>
      )}
    </section>
  );
}
