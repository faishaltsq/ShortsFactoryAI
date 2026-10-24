"use client";

import { useState } from "react";
import { api, ApiError } from "@/lib/api";

export function ApprovalControls({
  jobId,
  state,
  onDecision,
}: {
  jobId: string;
  state: string;
  onDecision: () => void;
}) {
  const [operator, setOperator] = useState("local-operator");
  const [reason, setReason] = useState("");
  const [busy, setBusy] = useState<"approve" | "reject" | null>(null);
  const [error, setError] = useState<string | null>(null);
  const [message, setMessage] = useState<string | null>(null);

  if (state !== "READY_FOR_APPROVAL") return null;

  const decide = async (decision: "approve" | "reject") => {
    const cleanOperator = operator.trim();
    const cleanReason = reason.trim();
    if (!cleanOperator || (decision === "reject" && !cleanReason)) {
      setError(decision === "reject" ? "Nama operator dan alasan penolakan wajib diisi." : "Nama operator wajib diisi.");
      return;
    }
    setBusy(decision);
    setError(null);
    setMessage(null);
    try {
      if (decision === "approve") {
        await api.approveJob(jobId, cleanOperator);
        setMessage("Job disetujui operator; kelayakan diverifikasi oleh server.");
      } else {
        await api.rejectJob(jobId, cleanOperator, cleanReason);
        setMessage("Job ditolak dan alasannya tercatat.");
      }
      onDecision();
    } catch (err) {
      setError(err instanceof ApiError ? err.message : "Keputusan gagal disimpan.");
    } finally {
      setBusy(null);
    }
  };

  return (
    <section className="px-frame space-y-4" aria-labelledby="approval-heading" data-testid="approval-controls">
      <div>
        <h2 id="approval-heading" className="text-lg font-medium">Keputusan operator</h2>
        <p className="mt-1 text-sm text-zinc-400">
          Persetujuan hanya berlaku setelah server memverifikasi artifact dan media yang tersimpan.
        </p>
      </div>
      <label className="block max-w-sm space-y-1 text-sm">
        <span className="text-xs text-zinc-500">Nama operator</span>
        <input
          value={operator}
          onChange={(event) => setOperator(event.target.value)}
          autoComplete="name"
          className="w-full rounded-md border border-zinc-700 bg-zinc-900 px-3 py-2"
          aria-label="Nama operator"
        />
      </label>
      <label className="block space-y-1 text-sm">
        <span className="text-xs text-zinc-500">Alasan penolakan</span>
        <textarea
          value={reason}
          onChange={(event) => setReason(event.target.value)}
          rows={2}
          maxLength={500}
          placeholder="Wajib diisi bila menolak"
          className="w-full rounded-md border border-zinc-700 bg-zinc-900 px-3 py-2"
          aria-label="Alasan penolakan"
        />
      </label>
      <div className="flex flex-wrap gap-2">
        <button
          type="button"
          onClick={() => void decide("approve")}
          disabled={busy !== null || !operator.trim()}
          className="px-button"
          data-primary="true"
        >
          {busy === "approve" ? "Memeriksa & menyetujui…" : "Setujui job"}
        </button>
        <button
          type="button"
          onClick={() => void decide("reject")}
          disabled={busy !== null || !operator.trim() || !reason.trim()}
          className="px-button border-rose-700 text-rose-300"
        >
          {busy === "reject" ? "Mencatat penolakan…" : "Tolak job"}
        </button>
      </div>
      {error && <p role="alert" className="text-sm text-rose-300">{error}</p>}
      {message && <p role="status" className="text-sm text-emerald-300">{message}</p>}
    </section>
  );
}
