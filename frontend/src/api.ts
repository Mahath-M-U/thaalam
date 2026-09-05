import type {
  BriefExplainerResponse,
  CycleRecord,
  DailyBriefResponse,
  DailyRecord,
  DerivedReadDiveResponse,
  DerivedReadsResponse,
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
