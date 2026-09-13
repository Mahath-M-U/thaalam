import type {
  BriefExplainerResponse,
  ChatReplyResponse,
  ChatStatusResponse,
  ChatStreamDone,
  ChatStreamMeta,
  ChatSuggestionsResponse,
  ChatTurn,
  CycleRecord,
  DailyBriefResponse,
  DailyRecord,
  DerivedReadDiveResponse,
  DerivedReadsResponse,
  HeadlineResponse,
  InsightsResponse,
  ProfileResponse,
  RecordsResponse,
  RecoveryRecord,
  RunwayResponse,
  SleepRecord,
  SleepStage,
  SportStrain,
  SummaryResponse,
  VitalityResponse,
  WorkoutRecord,
} from "./types";

export const CSRF_COOKIE = "thaalam_csrf";
const CSRF_HEADER = "X-CSRF-Token";
const SAFE_METHODS = new Set(["GET", "HEAD", "OPTIONS"]);

/** Notified when the server says the session is gone. */
let onUnauthorized: (() => void) | null = null;

export function setUnauthorizedHandler(handler: (() => void) | null): void {
  onUnauthorized = handler;
}

export class ApiError extends Error {
  constructor(
    message: string,
    readonly status: number,
  ) {
    super(message);
    this.name = "ApiError";
  }
}

function readCookie(name: string): string {
  const match = document.cookie.match(new RegExp(`(?:^|;\\s*)${name}=([^;]*)`));
  return match ? decodeURIComponent(match[1]) : "";
}

async function requestJson<T>(path: string, init?: RequestInit): Promise<T> {
  const method = (init?.method ?? "GET").toUpperCase();
  const headers = new Headers(init?.headers);

  // The CSRF cookie is readable on purpose: echoing it back as a header is
  // what a cross-site caller cannot do.
  if (!SAFE_METHODS.has(method)) {
    headers.set(CSRF_HEADER, readCookie(CSRF_COOKIE));
  }

  const res = await fetch(path, {
    ...init,
    headers,
    // Same-origin in production; the Vite proxy keeps dev same-origin too.
    credentials: "same-origin",
  });

  if (!res.ok) {
    let detail = res.statusText;
    try {
      const body = await res.json();
      detail = body.detail ?? JSON.stringify(body);
    } catch {
      /* ignore parse errors */
    }
    // Handled centrally so the dashboard's ~10 parallel reads collapse into
    // one trip back to the login screen rather than ten.
    if (res.status === 401) {
      onUnauthorized?.();
    }
    throw new ApiError(
      typeof detail === "string" ? detail : JSON.stringify(detail),
      res.status,
    );
  }
  if (res.status === 204) {
    return undefined as T;
  }
  return res.json() as Promise<T>;
}

/**
 * Read a `text/event-stream` body, one frame at a time.
 *
 * Deliberately hand-rolled rather than `EventSource`: that only does GET, and
 * the conversation has to travel in a POST body -- which is also what puts the
 * request behind the CSRF check.
 *
 * A frame is `event: <name>` and `data: <json>` separated by a blank line, so
 * the parse is a split on "\n\n" over a buffer that keeps whatever the last
 * chunk left unterminated.
 */
async function readEventStream(
  body: ReadableStream<Uint8Array>,
  onFrame: (event: string, data: Record<string, unknown>) => void,
): Promise<void> {
  const reader = body.getReader();
  const decoder = new TextDecoder();
  let buffer = "";

  try {
    for (;;) {
      const { done, value } = await reader.read();
      if (done) break;
      // `stream: true` matters: a token's UTF-8 bytes can straddle two chunks.
      buffer += decoder.decode(value, { stream: true });

      let boundary = buffer.indexOf("\n\n");
      while (boundary !== -1) {
        const block = buffer.slice(0, boundary);
        buffer = buffer.slice(boundary + 2);
        boundary = buffer.indexOf("\n\n");

        let name = "message";
        let data = "";
        for (const line of block.split("\n")) {
          if (line.startsWith("event:")) name = line.slice(6).trim();
          else if (line.startsWith("data:")) data += line.slice(5).trim();
          // Anything else is a comment keepalive or a field we do not use.
        }
        if (!data) continue;
        try {
          onFrame(name, JSON.parse(data) as Record<string, unknown>);
        } catch {
          /* a frame we cannot parse is not worth failing the answer over */
        }
      }
    }
  } finally {
    // Releasing matters on abort: without it the socket stays half-open.
    reader.releaseLock();
  }
}

export interface ChatStreamHandlers {
  /** Page scope and grounding, known before the model is called. */
  onMeta?: (meta: ChatStreamMeta) => void;
  /** The model that committed to the answer. */
  onStart?: (model: string) => void;
  /** Appended in order, as the model writes. */
  onDelta: (text: string) => void;
  /** The end. `error` set means the text above it is all there will be. */
  onDone?: (done: ChatStreamDone) => void;
}

/** Thrown when the server has no streaming route, so the caller can fall back. */
export class StreamUnsupported extends Error {
  constructor() {
    super("This server does not stream answers.");
    this.name = "StreamUnsupported";
  }
}

export interface CurrentUser {
  email: string;
  role: "admin" | "viewer";
  must_change_password: boolean;
  csrf_token: string;
}

export interface RegistrationStatus {
  first_run: boolean;
  invite_required: boolean;
  invite_valid: boolean;
}

export interface AdminInvite {
  id: number;
  email: string | null;
  role: "admin" | "viewer";
  created_at: string;
  expires_at: string;
  accepted_at: string | null;
  revoked_at: string | null;
}

export interface CreatedInvite {
  id: number;
  token: string;
  role: "admin" | "viewer";
  email: string | null;
  expires_in_hours: number;
}

export interface AdminUser {
  id: number;
  email: string;
  role: "admin" | "viewer";
  is_active: boolean;
  must_change_password: boolean;
  created_at: string;
  last_login_at: string | null;
}

export interface CreatedUser {
  user: AdminUser;
  temporary_password: string;
}

export interface AdminSession {
  id: number;
  email: string;
  role: string;
  created_at: string;
  last_seen_at: string;
  expires_at: string;
  client_ip: string | null;
  user_agent: string | null;
}

export interface AdminAuditEntry {
  id: number;
  created_at: string;
  event: string;
  actor_email: string | null;
  client_ip: string | null;
  request_id: string | null;
  detail: string | null;
}

export interface AdminAuditPage {
  total: number;
  entries: AdminAuditEntry[];
}

export interface AdminSystem {
  environment: string;
  whoop_connected: boolean;
  secure_cookies: boolean;
  session_ttl_minutes: number;
  database: { path: string; exists: boolean; size_bytes: number | null };
  auth_database: { path: string; size_bytes: number | null };
  accounts: { total: number; active_admins: number; active_sessions: number };
  last_recompute: { trigger: string; at: string } | null;
}

export const api = {
  health: () => requestJson<{ status: string; database_exists: boolean }>("/health"),
  summary: () => requestJson<SummaryResponse>("/api/summary"),
  profile: () => requestJson<ProfileResponse>("/api/profile"),
  recovery: () => requestJson<RecordsResponse<RecoveryRecord>>("/api/recovery"),
  cycles: () => requestJson<RecordsResponse<CycleRecord>>("/api/cycles"),
  daily: () => requestJson<RecordsResponse<DailyRecord>>("/api/daily"),
  sleep: () => requestJson<RecordsResponse<SleepRecord>>("/api/sleep"),
  workouts: () => requestJson<RecordsResponse<WorkoutRecord>>("/api/workouts"),
  sleepStages: () => requestJson<{ stages: SleepStage[]; nights?: number }>("/api/sleep/stages/average"),
  workoutsBySport: () => requestJson<{ sports: SportStrain[] }>("/api/workouts/by-sport"),
  insights: () => requestJson<InsightsResponse>("/api/insights"),
  // POST because it writes a row to insight_briefs, which puts it behind
  // CSRF protection.
  dailyBrief: () => requestJson<DailyBriefResponse>("/api/brief", { method: "POST" }),
  briefExplain: (question: string) =>
    requestJson<BriefExplainerResponse>(`/api/brief/explain?question=${encodeURIComponent(question)}`),
  sync: () => requestJson<{ ok: boolean }>("/api/sync", { method: "POST" }),
  // Ground truth for "is there a WHOOP token stored", so the dashboard can
  // tell "never connected" (offer Connect) apart from "connected, first
  // sync still running" (offer Check again) instead of showing the raw
  // 404/409 detail text either error produces. Admin-only server-side.
  whoopStatus: () => requestJson<{ connected: boolean }>("/api/oauth/whoop/status"),
  vitality: () => requestJson<VitalityResponse>("/api/derived/vitality"),
  derivedReads: () => requestJson<DerivedReadsResponse>("/api/derived/reads"),
  derivedReadDive: (id: string) =>
    requestJson<DerivedReadDiveResponse>(`/api/derived/reads/${encodeURIComponent(id)}`),
  derivedRunway: () => requestJson<RunwayResponse>("/api/derived/runway"),
  derivedHeadline: () => requestJson<HeadlineResponse>("/api/derived/headline"),

  // The assistant. `chatStatus` is what decides whether the dock renders at
  // all, so an install with no OPENROUTER_API_KEY shows no chat button rather
  // than one that fails when pressed.
  chatStatus: () => requestJson<ChatStatusResponse>("/api/chat/status"),
  chatSuggestions: (page: string) =>
    requestJson<ChatSuggestionsResponse>(
      `/api/chat/suggestions?page=${encodeURIComponent(page)}`,
    ),
  // POST: it spends the deployment's rationed free-tier allowance, which also
  // puts it behind CSRF protection. Only identifiers travel -- the server
  // reads every figure out of the database itself.
  chatSend: (
    body: {
      messages: ChatTurn[];
      page: string;
      read_id?: string | null;
      range_days?: number | null;
    },
    signal?: AbortSignal,
  ) =>
    requestJson<ChatReplyResponse>("/api/chat", {
      method: "POST",
      headers: { "Content-Type": "application/json" },
      body: JSON.stringify(body),
      signal,
    }),

  // The same question, answered as the model writes it. Resolves when the
  // answer is complete; rejects with `ApiError` if the request is refused
  // before the stream starts, or if it fails partway with nothing shown yet.
  // A refusal that arrives *inside* the stream (the free tier running dry
  // mid-answer) is an `error` frame, and rejects the same way -- the caller
  // keeps whatever `onDelta` already gave it.
  chatStream: async (
    body: {
      messages: ChatTurn[];
      page: string;
      read_id?: string | null;
      range_days?: number | null;
    },
    handlers: ChatStreamHandlers,
    signal?: AbortSignal,
  ): Promise<void> => {
    const res = await fetch("/api/chat/stream", {
      method: "POST",
      headers: {
        "Content-Type": "application/json",
        Accept: "text/event-stream",
        [CSRF_HEADER]: readCookie(CSRF_COOKIE),
      },
      body: JSON.stringify(body),
      credentials: "same-origin",
      signal,
    });

    if (res.status === 404 || res.status === 405) {
      // An older backend that only has the buffered route.
      throw new StreamUnsupported();
    }
    if (!res.ok || !res.body) {
      let detail = res.statusText;
      try {
        const parsed = await res.json();
        detail = parsed.detail ?? JSON.stringify(parsed);
      } catch {
        /* ignore parse errors */
      }
      if (res.status === 401) onUnauthorized?.();
      throw new ApiError(typeof detail === "string" ? detail : JSON.stringify(detail), res.status);
    }

    let failure: ApiError | null = null;
    await readEventStream(res.body, (event, data) => {
      switch (event) {
        case "meta":
          handlers.onMeta?.(data as unknown as ChatStreamMeta);
          break;
        case "start":
          handlers.onStart?.(String(data.model ?? ""));
          break;
        case "delta":
          if (typeof data.text === "string") handlers.onDelta(data.text);
          break;
        case "done":
          handlers.onDone?.(data as unknown as ChatStreamDone);
          break;
        case "error":
          failure = new ApiError(
            String(data.detail ?? "The assistant could not answer."),
            Number(data.status ?? 503),
          );
          break;
      }
    });
    if (failure) throw failure;
  },

  adminUsers: () => requestJson<AdminUser[]>("/api/admin/users"),
  adminCreateUser: (email: string, role: AdminUser["role"]) =>
    requestJson<CreatedUser>("/api/admin/users", {
      method: "POST",
      headers: { "Content-Type": "application/json" },
      body: JSON.stringify({ email, role }),
    }),
  adminUpdateUser: (id: number, patch: { role?: string; is_active?: boolean }) =>
    requestJson<AdminUser>(`/api/admin/users/${id}`, {
      method: "PATCH",
      headers: { "Content-Type": "application/json" },
      body: JSON.stringify(patch),
    }),
  adminResetPassword: (id: number) =>
    requestJson<CreatedUser>(`/api/admin/users/${id}/reset-password`, { method: "POST" }),
  adminSessions: () => requestJson<AdminSession[]>("/api/admin/sessions"),
  adminRevokeSession: (id: number) =>
    requestJson<void>(`/api/admin/sessions/${id}`, { method: "DELETE" }),
  adminAudit: (limit = 50, event?: string) =>
    requestJson<AdminAuditPage>(
      `/api/admin/audit?limit=${limit}${event ? `&event=${encodeURIComponent(event)}` : ""}`,
    ),
  adminSystem: () => requestJson<AdminSystem>("/api/admin/system"),

  registrationStatus: (invite?: string) =>
    requestJson<RegistrationStatus>(
      `/api/auth/registration${invite ? `?invite=${encodeURIComponent(invite)}` : ""}`,
    ),
  register: (email: string, password: string, inviteToken?: string) =>
    requestJson<CurrentUser>("/api/auth/register", {
      method: "POST",
      headers: { "Content-Type": "application/json" },
      body: JSON.stringify({
        email,
        password,
        invite_token: inviteToken || null,
      }),
    }),
  adminInvites: () => requestJson<AdminInvite[]>("/api/admin/invites"),
  adminCreateInvite: (role: AdminUser["role"], email?: string) =>
    requestJson<CreatedInvite>("/api/admin/invites", {
      method: "POST",
      headers: { "Content-Type": "application/json" },
      body: JSON.stringify({ role, email: email || null }),
    }),
  adminRevokeInvite: (id: number) =>
    requestJson<void>(`/api/admin/invites/${id}`, { method: "DELETE" }),

  me: () => requestJson<CurrentUser>("/api/auth/me"),
  login: (email: string, password: string) =>
    requestJson<CurrentUser>("/api/auth/login", {
      method: "POST",
      headers: { "Content-Type": "application/json" },
      body: JSON.stringify({ email, password }),
    }),
  logout: () => requestJson<void>("/api/auth/logout", { method: "POST" }),
  changePassword: (currentPassword: string, newPassword: string) =>
    requestJson<CurrentUser>("/api/auth/password", {
      method: "POST",
      headers: { "Content-Type": "application/json" },
      body: JSON.stringify({
        current_password: currentPassword,
        new_password: newPassword,
      }),
    }),
};
