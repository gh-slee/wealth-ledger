// Same-origin transport for the V2 identity API. The CSRF token is kept only
// in memory. Clearing the transport aborts every request that is still in
// flight, so a response from an earlier session can never be rendered.

export type Role = "instance_admin" | "member";
export type Me = {
  authenticated: true;
  user: { id: string; username: string; role: Role };
  portfolio: { id: string };
};
export type InvitationState = "issued" | "expired" | "revoked" | "consumed";
export type Invitation = {
  id: string;
  issue_request_id: string | null;
  created_at: string;
  expires_at: string;
  status: InvitationState;
  revocation_reason: "manual" | "restore" | null;
};
export type Invitations = { items: Invitation[]; next_after: string | null };
export type InvitationIssued = {
  id: string;
  issue_request_id: string;
  invite_token: string;
  expires_at: string;
};

export const UNAUTHORIZED_EVENT = "kurafolio-v2:unauthorized";

export class V2Error extends Error {
  constructor(
    public status: number,
    public code: string,
  ) {
    super(code);
  }
}

// These requests run without a signed-in session, so a 401 from them is an
// answer to the form, not a sign that a session ended.
const anonymous = new Set([
  "/auth/csrf",
  "/auth/login",
  "/auth/setup",
  "/auth/register",
]);
// The server clears the session cookie after these succeed, which also
// invalidates the CSRF token bound to it.
const cookieResets = new Set([
  "/auth/setup",
  "/auth/register",
  "/auth/logout",
  "/auth/password",
]);

let csrf: string | null = null;
let generation = 0;
const controllers = new Set<AbortController>();

export function clearTransport() {
  generation++;
  csrf = null;
  for (const controller of controllers) controller.abort();
  controllers.clear();
}

function changed(started: number) {
  if (started !== generation)
    throw new DOMException("Request context changed", "AbortError");
}

async function transport<T>(
  path: string,
  init: RequestInit = {},
  signal?: AbortSignal,
): Promise<T> {
  const controller = new AbortController();
  controllers.add(controller);
  const abort = () => controller.abort();
  signal?.addEventListener("abort", abort, { once: true });
  if (signal?.aborted) controller.abort();
  const started = generation;
  try {
    const response = await fetch("/api/v2" + path, {
      ...init,
      headers: { Accept: "application/json", ...init.headers },
      credentials: "same-origin",
      cache: "no-store",
      redirect: "error",
      signal: controller.signal,
    });
    changed(started);
    if (!response.ok) {
      const value = await response.json().catch(() => null);
      changed(started);
      const code =
        typeof value?.error?.code === "string"
          ? value.error.code
          : "request_failed";
      if (response.status === 401) {
        if (anonymous.has(path.split("?")[0])) csrf = null;
        else {
          clearTransport();
          window.dispatchEvent(new Event(UNAUTHORIZED_EVENT));
        }
      }
      throw new V2Error(response.status, code);
    }
    const value =
      response.status === 204 ? undefined : await response.json();
    changed(started);
    return value as T;
  } finally {
    controllers.delete(controller);
    signal?.removeEventListener("abort", abort);
  }
}

export function read<T>(path: string, signal?: AbortSignal): Promise<T> {
  return transport<T>(path, {}, signal);
}

async function csrfToken() {
  if (csrf) return csrf;
  const started = generation;
  const value = await transport<{ csrf_token: string }>("/auth/csrf");
  changed(started);
  csrf = value.csrf_token;
  return csrf;
}

export async function mutate<T>(path: string, body: unknown = {}): Promise<T> {
  for (let attempt = 0; ; attempt++) {
    const started = generation;
    const token = await csrfToken();
    changed(started);
    try {
      const value = await transport<T>(path, {
        method: "POST",
        headers: { "Content-Type": "application/json", "X-CSRF-Token": token },
        body: JSON.stringify(body),
      });
      const replacement = (value as { csrf_token?: unknown } | undefined)
        ?.csrf_token;
      if (typeof replacement === "string") csrf = replacement;
      else if (cookieResets.has(path)) csrf = null;
      return value;
    } catch (error) {
      // The server rejects a token before running the handler, so asking for
      // a fresh one and sending the same request once more is safe.
      if (
        attempt === 0 &&
        error instanceof V2Error &&
        error.code === "csrf_rejected"
      ) {
        csrf = null;
        continue;
      }
      throw error;
    }
  }
}
