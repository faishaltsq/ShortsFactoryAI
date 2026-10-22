import { act, renderHook, waitFor } from "@testing-library/react";
import { afterEach, expect, it, vi } from "vitest";

import { api } from "./api";
import { useStudioLive } from "./useStudioLive";

afterEach(() => {
  vi.restoreAllMocks();
  vi.useRealTimers();
});

it("aborts the in-flight request on unmount", async () => {
  const list = vi.spyOn(api, "listJobs").mockImplementation(() => new Promise(() => {}));
  const { unmount } = renderHook(() => useStudioLive());
  await waitFor(() => expect(list).toHaveBeenCalledTimes(1));
  const signal = list.mock.calls[0][1]!;
  unmount();
  expect(signal.aborted).toBe(true);
});

it("retains stale state and stops automatic retries after three failures", async () => {
  vi.useFakeTimers();
  const list = vi.spyOn(api, "listJobs").mockRejectedValue(new Error("offline"));
  const { result, unmount } = renderHook(() => useStudioLive());
  await act(async () => {
    await vi.advanceTimersByTimeAsync(30000);
  });
  expect(list).toHaveBeenCalledTimes(3);
  expect(result.current.stale).toBe(true);
  expect(result.current.error).toBeTruthy();
  await act(async () => {
    result.current.retry();
  });
  expect(list).toHaveBeenCalledTimes(4);
  unmount();
});
