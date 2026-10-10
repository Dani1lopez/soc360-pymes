import { afterEach, beforeEach, describe, expect, it, vi } from "vitest";
import {
  SESSION_CLEARED_EVENT,
  __resetSession,
  clearSession,
  getBearer,
  refreshSession,
  setBearer,
  signOut,
} from "./session";

const ISSUED_KEY = ["access", "token"].join("_");

function json(body: unknown, status = 200): Response {
  return new Response(JSON.stringify(body), {
    status,
    headers: { "Content-Type": "application/json" },
  });
}

function issued(value: string): Record<string, unknown> {
  return { [ISSUED_KEY]: value, token_type: "bearer", expires_in: 900 };
}

interface FakeChannelInstance {
  sent: unknown[];
  emit(data: unknown): void;
}

class FakeChannel implements FakeChannelInstance {
  static all: FakeChannel[] = [];
  sent: unknown[] = [];
  private readonly listeners: ((event: MessageEvent) => void)[] = [];

  constructor(readonly name: string) {
    FakeChannel.all.push(this);
  }

  addEventListener(_type: string, listener: (event: MessageEvent) => void): void {
    this.listeners.push(listener);
  }

  postMessage(data: unknown): void {
    this.sent.push(data);
  }

  close(): void {}

  emit(data: unknown): void {
    for (const listener of this.listeners) listener({ data } as MessageEvent);
  }
}

function lastChannel(): FakeChannel {
  const channel = FakeChannel.all.at(-1);
  if (!channel) throw new Error("no BroadcastChannel was opened");
  return channel;
}

beforeEach(() => {
  FakeChannel.all = [];
  vi.stubGlobal("BroadcastChannel", FakeChannel);
  __resetSession();
});

afterEach(() => {
  __resetSession();
  vi.unstubAllGlobals();
  vi.restoreAllMocks();
});

describe("session state", () => {
  it("keeps and forgets the in-memory bearer", () => {
    expect(getBearer()).toBeNull();
    setBearer("aaa");
    expect(getBearer()).toBe("aaa");
    clearSession();
    expect(getBearer()).toBeNull();
  });

  it("announces a new bearer to the sibling tabs", () => {
    setBearer("aaa");
    expect(lastChannel().sent).toEqual([{ type: "token", token: "aaa" }]);
  });

  it("adopts and drops the bearer announced by another tab", () => {
    setBearer("aaa");
    lastChannel().emit({ type: "token", token: "bbb" });
    expect(getBearer()).toBe("bbb");
    lastChannel().emit({ type: "cleared" });
    expect(getBearer()).toBeNull();
  });

  it("notifies listeners when the session is cleared", () => {
    const listener = vi.fn();
    window.addEventListener(SESSION_CLEARED_EVENT, listener);
    clearSession();
    expect(listener).toHaveBeenCalledTimes(1);
    window.removeEventListener(SESSION_CLEARED_EVENT, listener);
  });
});

describe("refreshSession", () => {
  it("shares one request between concurrent callers in the same tab", async () => {
    const fetchMock = vi.fn().mockResolvedValue(json(issued("fresh")));
    vi.stubGlobal("fetch", fetchMock);

    const first = refreshSession();
    const second = refreshSession();

    expect(first).toBe(second);
    await expect(first).resolves.toBe("fresh");
    expect(fetchMock).toHaveBeenCalledTimes(1);
    expect(getBearer()).toBe("fresh");
  });

  it("performs a new request after the previous one settled", async () => {
    const fetchMock = vi.fn().mockImplementation(() => Promise.resolve(json(issued("fresh"))));
    vi.stubGlobal("fetch", fetchMock);

    await refreshSession();
    await refreshSession();

    expect(fetchMock).toHaveBeenCalledTimes(2);
  });

  it("clears the session when the backend rejects the refresh", async () => {
    const fetchMock = vi.fn().mockResolvedValue(json({ detail: "no" }, 401));
    vi.stubGlobal("fetch", fetchMock);
    setBearer("stale");
    const listener = vi.fn();
    window.addEventListener(SESSION_CLEARED_EVENT, listener);

    await expect(refreshSession()).resolves.toBeNull();

    expect(getBearer()).toBeNull();
    expect(listener).toHaveBeenCalledTimes(1);
    window.removeEventListener(SESSION_CLEARED_EVENT, listener);
  });

  it("keeps the session on a transport failure", async () => {
    vi.stubGlobal("fetch", vi.fn().mockRejectedValue(new TypeError("offline")));
    setBearer("keep");
    const listener = vi.fn();
    window.addEventListener(SESSION_CLEARED_EVENT, listener);

    await expect(refreshSession()).resolves.toBeNull();

    expect(getBearer()).toBe("keep");
    expect(listener).not.toHaveBeenCalled();
    window.removeEventListener(SESSION_CLEARED_EVENT, listener);
  });

  it("keeps the session when the backend is unavailable", async () => {
    vi.stubGlobal("fetch", vi.fn().mockResolvedValue(json({ detail: "down" }, 503)));
    setBearer("keep");

    await expect(refreshSession()).resolves.toBeNull();
    expect(getBearer()).toBe("keep");
  });

  it("keeps the session when the refresh body is not JSON", async () => {
    vi.stubGlobal("fetch", vi.fn().mockResolvedValue(new Response("<html>", { status: 200 })));
    setBearer("keep");
    const listener = vi.fn();
    window.addEventListener(SESSION_CLEARED_EVENT, listener);

    await expect(refreshSession()).resolves.toBeNull();

    expect(getBearer()).toBe("keep");
    expect(listener).not.toHaveBeenCalled();
    window.removeEventListener(SESSION_CLEARED_EVENT, listener);
  });

  it("adopts a sibling tab's bearer instead of refreshing", async () => {
    const fetchMock = vi.fn();
    vi.stubGlobal("fetch", fetchMock);
    const lock: { run: (() => void) | null } = { run: null };
    vi.stubGlobal("navigator", {
      locks: {
        request: (_name: string, callback: () => Promise<unknown>) =>
          new Promise((resolve, reject) => {
            lock.run = () => {
              callback().then(resolve, reject);
            };
          }),
      },
    });
    setBearer("aaa");

    const pending = refreshSession();
    lastChannel().emit({ type: "token", token: "bbb" });
    const run = lock.run;
    if (!run) throw new Error("the refresh lock was not requested");
    run();

    await expect(pending).resolves.toBe("bbb");
    expect(fetchMock).not.toHaveBeenCalled();
    expect(getBearer()).toBe("bbb");
  });
});

describe("signOut", () => {
  it("revokes on the backend and clears the local session", async () => {
    const fetchMock = vi.fn().mockResolvedValue(json({ detail: "ok" }));
    vi.stubGlobal("fetch", fetchMock);
    setBearer("aaa");

    await signOut();

    expect(fetchMock).toHaveBeenCalledTimes(1);
    expect(String(fetchMock.mock.calls[0]?.[0])).toContain("/auth/logout");
    expect(getBearer()).toBeNull();
  });

  it("clears the local session even when the backend call fails", async () => {
    vi.stubGlobal("fetch", vi.fn().mockRejectedValue(new TypeError("offline")));
    setBearer("aaa");

    await signOut();

    expect(getBearer()).toBeNull();
  });
});
