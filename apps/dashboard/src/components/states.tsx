"use client";

import type { ReactNode } from "react";

const STATE_STYLES: Record<string, string> = {
  READY_FOR_APPROVAL: "border-emerald-700 bg-emerald-950 text-emerald-300",
  APPROVED: "border-emerald-700 bg-emerald-950 text-emerald-300",
  PUBLISHED: "border-emerald-700 bg-emerald-950 text-emerald-300",
  FAILED: "border-rose-800 bg-rose-950 text-rose-300",
  BLOCKED: "border-amber-800 bg-amber-950 text-amber-300",
  REJECTED: "border-rose-800 bg-rose-950 text-rose-300",
  CANCELLED: "border-zinc-700 bg-zinc-900 text-zinc-400",
};

export function StateChip({ state }: { state: string }) {
  const style = STATE_STYLES[state] ?? "border-zinc-700 bg-zinc-900 text-zinc-300";
  return (
    <span className={`px-chip ${style}`}>
      {state}
    </span>
  );
}

export function EmptyState({
  title,
  description,
  action,
}: {
  title: string;
  description: string;
  action?: ReactNode;
}) {
  return (
    <div className="px-frame border-dashed py-10 text-center">
      <p className="text-base font-medium text-zinc-200">{title}</p>
      <p className="mx-auto mt-2 max-w-md text-sm text-zinc-500">{description}</p>
      {action && <div className="mt-4 flex justify-center">{action}</div>}
    </div>
  );
}

export function ErrorState({
  title,
  message,
  onRetry,
}: {
  title: string;
  message: string;
  onRetry?: () => void;
}) {
  return (
    <div className="px-frame border-rose-800 bg-rose-950/40" role="alert">
      <p className="text-sm font-medium text-rose-200">{title}</p>
      <p className="mt-1 break-words text-xs text-rose-300/80">{message}</p>
      {onRetry && (
        <button
          onClick={onRetry}
          className="px-button mt-3"
        >
          Coba lagi
        </button>
      )}
    </div>
  );
}

export function LoadingState({ label }: { label: string }) {
  return (
    <p className="text-sm text-zinc-500" role="status">
      {label}
    </p>
  );
}
