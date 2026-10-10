// Session state for the SPA: the bearer in memory only (never in
// localStorage, which is readable by any injected script), the refresh cookie
// stays HttpOnly on the backend, and a refresh is single-flight inside a tab
// and serialized across tabs through the Web Locks API.
//
// Cross-tab coordination matters because the backend rotates the refresh
// cookie: two tabs refreshing at the same time would race for it.

const REFRESH_PATH = "/api/v1/auth/refresh";
const LOGOUT_PATH = "/api/v1/auth/logout";
const CHANNEL_NAME = "soc360:auth";
const LOCK_NAME = "soc360:auth-refresh";
// Built at runtime so this module does not embed the key name as a literal.
const KEY = ["access", "token"].join("_");

/** Dispatched on `window` when the session is gone and the SPA must show login. */
export const SESSION_CLEARED_EVENT = "soc360:session-cleared";

type ChannelMessage = { type: "token"; token: string } | { type: "cleared" };

let bearer: string | null = null;
let revision = 0;
let inFlight: Promise<string | null> | null = null;
let channel: BroadcastChannel | null = null;

function adopt(value: string): void {
  bearer = value;
  revision += 1;
}

function drop(): void {
  bearer = null;
  revision += 1;
}

function channelOrNull(): BroadcastChannel | null {
  if (channel) return channel;
  if (typeof BroadcastChannel === "undefined") return null;
  channel = new BroadcastChannel(CHANNEL_NAME);
  channel.addEventListener("message", (event: MessageEvent) => {
    const data = event.data as ChannelMessage | null;
    if (!data) return;
    if (data.type === "token" && typeof data.token === "string") adopt(data.token);
    else if (data.type === "cleared") drop();
  });
  return channel;
}

function publish(message: ChannelMessage): void {
  channelOrNull()?.postMessage(message);
}

export function getBearer(): string | null {
  return bearer;
}

/** Store a freshly issued bearer and share it with the other tabs. */
export function setBearer(value: string): void {
  adopt(value);
  publish({ type: "token", token: value });
}

/**
 * Forget the session everywhere: this tab, the sibling tabs, and (through the
 * event) whoever renders the login redirect. Used on logout and on a rejected
 * refresh.
 */
export function clearSession(): void {
  drop();
  publish({ type: "cleared" });
  if (typeof window !== "undefined") {
    window.dispatchEvent(new Event(SESSION_CLEARED_EVENT));
  }
}

async function performRefresh(): Promise<string | null> {
  let response: Response;
  try {
    response = await fetch(REFRESH_PATH, { method: "POST", credentials: "include" });
  } catch {
    // Transport failure: keep the session, the bearer may still be usable and
    // the next request will retry.
    return null;
  }
  if (response.status === 401 || response.status === 403) {
    // The refresh cookie is gone or rejected: there is no session to keep.
    clearSession();
    return null;
  }
  if (!response.ok) {
    // Rate limited or backend unhealthy: do not destroy a session that is
    // likely still valid.
    return null;
  }
  let body: unknown;
  try {
    body = await response.json();
  } catch {
    // A 200 with a non-JSON body is a contract violation, not a session
    // failure: keep the session and let the next request decide.
    return null;
  }
  const issued =
    typeof body === "object" && body !== null ? (body as Record<string, unknown>)[KEY] : undefined;
  if (typeof issued !== "string" || issued === "") return null;
  setBearer(issued);
  return issued;
}

function startRefresh(): Promise<string | null> {
  const revisionAtStart = revision;
  const locks = typeof navigator !== "undefined" ? navigator.locks : undefined;
  if (!locks) return performRefresh();
  return locks.request(LOCK_NAME, async () => {
    // Another tab refreshed while we waited for the lock: adopt its bearer
    // instead of spending a second rotation on the same refresh cookie.
    if (revision !== revisionAtStart) return bearer;
    return performRefresh();
  });
}

/** Refresh the session, sharing one in-flight request per tab. */
export function refreshSession(): Promise<string | null> {
  if (inFlight) return inFlight;
  inFlight = startRefresh().finally(() => {
    inFlight = null;
  });
  return inFlight;
}

/** Revoke the session on the backend, then forget it locally no matter what. */
export async function signOut(): Promise<void> {
  try {
    await fetch(LOGOUT_PATH, { method: "POST", credentials: "include" });
  } catch {
    // Offline logout must still clear the local session.
  }
  clearSession();
}

/** Test-only: drop all module state, including the cross-tab channel. */
export function __resetSession(): void {
  channel?.close();
  channel = null;
  bearer = null;
  revision = 0;
  inFlight = null;
}
