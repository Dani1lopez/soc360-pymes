import { describe, expect, it } from "vitest";
import {
  SCAN_POLL_BASE_MS,
  SCAN_POLL_MAX_MS,
  hasActiveScans,
  isActiveScan,
  nextPollDelay,
  pollingInterval,
} from "./polling";

describe("isActiveScan", () => {
  it("considers pending and running open", () => {
    expect(isActiveScan("pending")).toBe(true);
    expect(isActiveScan("running")).toBe(true);
  });

  it("treats terminal states and unknown values as closed", () => {
    expect(isActiveScan("completed")).toBe(false);
    expect(isActiveScan("failed")).toBe(false);
    expect(isActiveScan("cancelled")).toBe(false);
    expect(isActiveScan("queued")).toBe(false);
  });
});

describe("pollingInterval", () => {
  it("stops the poll when nothing is open", () => {
    expect(
      pollingInterval([{ status: "completed" }, { status: "failed" }], SCAN_POLL_BASE_MS),
    ).toBe(false);
    expect(pollingInterval([], SCAN_POLL_BASE_MS)).toBe(false);
    expect(pollingInterval(undefined, SCAN_POLL_BASE_MS)).toBe(false);
  });

  it("keeps polling while something is open", () => {
    expect(pollingInterval([{ status: "running" }], 10_000)).toBe(10_000);
    expect(hasActiveScans([{ status: "completed" }, { status: "pending" }])).toBe(true);
  });
});

describe("nextPollDelay", () => {
  it("backs off exponentially up to the ceiling", () => {
    expect(nextPollDelay(5_000)).toBe(10_000);
    expect(nextPollDelay(10_000)).toBe(20_000);
    expect(nextPollDelay(20_000)).toBe(30_000);
    expect(nextPollDelay(30_000)).toBe(SCAN_POLL_MAX_MS);
  });
});
