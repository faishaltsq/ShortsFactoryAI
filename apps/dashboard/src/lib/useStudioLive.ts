"use client";

import { useCallback, useEffect, useRef, useState } from "react";

import { api, type JobDetail, type JobRow } from "./api";

const POLL_MS = 2500;
const TIMEOUT_MS = 10000;
const MAX_FAILURES = 3;

/**
 * Observes the API's latest-job window. Never writes configuration and never
 * starts work; the operator's own actions go through `useStudio` and the API.
 *
 * Failure policy: three consecutive errors set `stale` and stop the automatic
 * loop, keeping the last good data on screen. `retry()` restarts it.
 */
export function useStudioLive() {
  const [jobs, setJobs] = useState<JobRow[]>([]);
  const [focusId, setFocusId] = useState("");
  const [detail, setDetail] = useState<JobDetail | null>(null);
  const [error, setError] = useState<string | null>(null);
  const [stale, setStale] = useState(false);
  const [loading, setLoading] = useState(true);
  const [revision, setRevision] = useState(0);
  const selected = useRef("");

  const selectJob = useCallback((id: string) => {
    selected.current = id;
    setFocusId(id);
    setDetail(null);
    setLoading(true);
    setRevision((v) => v + 1);
  }, []);

  const retry = useCallback(() => setRevision((v) => v + 1), []);

  useEffect(() => {
    let alive = true;
    let failures = 0;
    let timer: ReturnType<typeof setTimeout> | undefined;
    let controller: AbortController | null = null;
    let busy = false;

    const poll = async () => {
      if (!alive || busy || document.hidden || failures >= MAX_FAILURES) return;
      busy = true;
      controller = new AbortController();
      const signal = controller.signal;
      const timeout = setTimeout(() => controller?.abort(), TIMEOUT_MS);
      try {
        const list = await api.listJobs(undefined, signal);
        const existing = list.jobs.find((j) => j.id === selected.current);
        const target = existing ?? list.jobs.find((j) => list.running[j.id]) ?? list.jobs[0];
        const next = target ? await api.getJob(target.id, signal) : null;
        if (!alive || signal.aborted) return;
        selected.current = target?.id ?? "";
        setFocusId(selected.current);
        setJobs(list.jobs);
        setDetail(next);
        setError(null);
        setStale(false);
        failures = 0;
      } catch {
        if (!alive || document.hidden) return;
        failures += 1;
        setStale(true);
        setError("Aktivitas belum bisa diperbarui. Data terakhir tetap ditampilkan.");
      } finally {
        clearTimeout(timeout);
        busy = false;
        if (alive) {
          setLoading(false);
          if (!document.hidden && failures < MAX_FAILURES) {
            timer = setTimeout(() => void poll(), failures ? POLL_MS * 2 ** failures : POLL_MS);
          }
        }
      }
    };

    const visibility = () => {
      clearTimeout(timer);
      if (document.hidden) {
        controller?.abort();
      } else {
        failures = 0;
        void poll();
      }
    };

    document.addEventListener("visibilitychange", visibility);
    void poll();
    return () => {
      alive = false;
      clearTimeout(timer);
      controller?.abort();
      document.removeEventListener("visibilitychange", visibility);
    };
  }, [revision]);

  return { jobs, focusId, detail, error, stale, loading, selectJob, retry };
}
