"use client";

import type { ReactNode } from "react";

export function Section({
  title,
  description,
  children,
}: {
  title: string;
  description?: string;
  children: ReactNode;
}) {
  return (
    <section className="rounded-xl border border-zinc-800 bg-zinc-900/40 p-6">
      <h2 className="text-lg font-medium">{title}</h2>
      {description && <p className="mb-4 mt-1 text-sm text-zinc-400">{description}</p>}
      <div className="mt-4">{children}</div>
    </section>
  );
}

export function FieldRow({
  label,
  hint,
  error,
  children,
}: {
  label: string;
  hint?: string;
  error?: string | null;
  children: ReactNode;
}) {
  return (
    <label className="block space-y-1.5">
      <span className="text-sm font-medium text-zinc-200">{label}</span>
      {children}
      {error ? (
        <span className="block text-xs text-rose-400" role="alert">
          {error}
        </span>
      ) : hint ? (
        <span className="block text-xs text-zinc-500">{hint}</span>
      ) : null}
    </label>
  );
}

export function NumberInput({
  label,
  value,
  placeholder,
  step = 1,
  error,
  onChange,
}: {
  label: string;
  value: string | number;
  placeholder: string;
  step?: number;
  error?: string | null;
  onChange: (v: number | null) => void;
}) {
  return (
    <FieldRow label={label} hint={`Default aktif: ${placeholder}`} error={error}>
      <input
        type="number"
        step={step}
        value={value}
        placeholder={placeholder}
        onChange={(e) => onChange(e.target.value === "" ? null : Number(e.target.value))}
        className="w-full rounded-md border border-zinc-700 bg-zinc-900 px-3 py-2 text-sm outline-none focus:border-sky-500 focus-visible:ring-2 focus-visible:ring-sky-500"
      />
    </FieldRow>
  );
}

export function PromptEditor({
  value,
  defaultValue,
  onChange,
  onReset,
  error,
}: {
  value: string;
  defaultValue: string;
  onChange: (text: string) => void;
  onReset: () => void;
  error?: string | null;
}) {
  const overridden = value.trim().length > 0 && value !== defaultValue;
  return (
    <div className="mt-4">
      <div className="mb-1.5 flex items-center justify-between">
        <span className="text-sm font-medium text-zinc-200">
          System prompt {overridden && <span className="ml-1 text-xs text-amber-400">di-override</span>}
        </span>
        <button
          type="button"
          onClick={onReset}
          className="rounded-md border border-zinc-700 px-2 py-1 text-xs text-zinc-300 transition hover:bg-zinc-800 focus-visible:ring-2 focus-visible:ring-sky-500"
        >
          Kembalikan ke default
        </button>
      </div>
      <textarea
        value={value}
        onChange={(e) => onChange(e.target.value)}
        rows={8}
        spellCheck={false}
        placeholder={defaultValue}
        className={`w-full rounded-md border bg-zinc-900 px-3 py-2 font-mono text-xs leading-relaxed outline-none focus:border-sky-500 ${
          error ? "border-rose-500" : "border-zinc-700"
        }`}
      />
      <div className="mt-1 flex justify-between text-xs text-zinc-500">
        <span>
          {error ? (
            <span className="text-rose-400" role="alert">
              {error}
            </span>
          ) : (
            "Kosong = memakai prompt default sistem"
          )}
        </span>
        <span>{value.length} karakter</span>
      </div>
    </div>
  );
}

export function Toast({
  toast,
  onClose,
}: {
  toast: { kind: "ok" | "error"; text: string } | null;
  onClose: () => void;
}) {
  if (!toast) return null;
  return (
    <div
      role="status"
      aria-live="polite"
      className={`fixed bottom-6 right-6 max-w-sm rounded-lg border px-4 py-3 text-sm shadow-xl ${
        toast.kind === "ok"
          ? "border-emerald-700 bg-emerald-950 text-emerald-100"
          : "border-rose-700 bg-rose-950 text-rose-100"
      }`}
    >
      <div className="flex items-start gap-4">
        <p>{toast.text}</p>
        <button onClick={onClose} className="text-xs underline opacity-70 hover:opacity-100">
          tutup
        </button>
      </div>
    </div>
  );
}
