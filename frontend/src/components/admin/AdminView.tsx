import { useCallback, useEffect, useState } from "react";
import {
  api,
  type AdminAuditEntry,
  type AdminInvite,
  type AdminSession,
  type AdminSystem,
  type AdminUser,
} from "../../api";
import type { AdminTab } from "../../routes";
import { Section } from "../Section";

const TABS: { id: AdminTab; label: string }[] = [
  { id: "users", label: "Accounts" },
  { id: "sessions", label: "Sessions" },
  { id: "audit", label: "Audit" },
  { id: "system", label: "System" },
];

interface Props {
  tab: AdminTab;
  onTab: (tab: AdminTab) => void;
  onClose: () => void;
}

export function AdminView({ tab, onTab, onClose }: Props) {
  return (
    <div className="admin-view">
      <header className="admin-head">
        <div>
          <div className="admin-kicker">Administration</div>
          <h2>Who can see this, and what happened</h2>
        </div>
        <button type="button" className="btn ghost" onClick={onClose}>
          Back to dashboard
        </button>
      </header>

      <div className="range-chips" role="group" aria-label="Admin section">
        {TABS.map((item) => (
          <button
            key={item.id}
            type="button"
            className={tab === item.id ? "active" : ""}
            onClick={() => onTab(item.id)}
          >
            {item.label}
          </button>
        ))}
      </div>

      {tab === "users" ? (
        <>
          <UsersPanel />
          <InvitesPanel />
        </>
      ) : null}
      {tab === "sessions" ? <SessionsPanel /> : null}
      {tab === "audit" ? <AuditPanel /> : null}
      {tab === "system" ? <SystemPanel /> : null}
    </div>
  );
}

/** Shared loading/error/empty handling, matching the dashboard's panels. */
function useResource<T>(load: () => Promise<T>) {
  const [data, setData] = useState<T | null>(null);
  const [error, setError] = useState("");
  const [loading, setLoading] = useState(true);

  const refresh = useCallback(() => {
    setLoading(true);
    load()
      .then((value) => {
        setData(value);
        setError("");
      })
      .catch((err) => setError(err instanceof Error ? err.message : "Could not load"))
      .finally(() => setLoading(false));
    // `load` is recreated per render by callers; depending on it would loop.
    // eslint-disable-next-line react-hooks/exhaustive-deps
  }, []);

  useEffect(refresh, [refresh]);
  return { data, error, loading, refresh };
}

function Panel({
  loading,
  error,
  children,
}: {
  loading: boolean;
  error: string;
  children: React.ReactNode;
}) {
  if (loading) {
    return (
      <div className="state-panel">
        <span className="spinner" />
        <p>Loading…</p>
      </div>
    );
  }
  if (error) {
    return (
      <div className="state-panel error">
        <h2>Could not load data</h2>
        <p className="muted">{error}</p>
      </div>
    );
  }
  return <>{children}</>;
}

function UsersPanel() {
  const { data, error, loading, refresh } = useResource<AdminUser[]>(() => api.adminUsers());
  const [email, setEmail] = useState("");
  const [role, setRole] = useState<AdminUser["role"]>("viewer");
  const [handover, setHandover] = useState<{ email: string; password: string } | null>(null);
  const [actionError, setActionError] = useState("");

  const run = async (work: () => Promise<void>) => {
    setActionError("");
    try {
      await work();
      refresh();
    } catch (err) {
      setActionError(err instanceof Error ? err.message : "That did not work");
    }
  };

  return (
    <Section id="admin-users" title="Accounts">
      <div className="chart-card wide">
        <form
          className="admin-invite"
          onSubmit={(event) => {
            event.preventDefault();
            void run(async () => {
              const created = await api.adminCreateUser(email, role);
              setHandover({
                email: created.user.email,
                password: created.temporary_password,
              });
              setEmail("");
            });
          }}
        >
          <input
            type="email"
            required
            placeholder="person@example.com"
            value={email}
            onChange={(event) => setEmail(event.target.value)}
          />
          <select value={role} onChange={(event) => setRole(event.target.value as AdminUser["role"])}>
            <option value="viewer">Viewer</option>
            <option value="admin">Admin</option>
          </select>
          <button type="submit" className="btn">
            Invite
          </button>
        </form>

        {handover ? (
          <p className="admin-handover">
            One-time password for <strong>{handover.email}</strong>:{" "}
            <code>{handover.password}</code> — it is shown once and must be
            changed at first sign-in.
          </p>
        ) : null}
        {actionError ? <p className="auth-error">{actionError}</p> : null}

        <Panel loading={loading} error={error}>
          <table className="data-table">
            <thead>
              <tr>
                <th>Email</th>
                <th>Role</th>
                <th>Status</th>
                <th>Last sign-in</th>
                <th />
              </tr>
            </thead>
            <tbody>
              {(data ?? []).map((user) => (
                <tr key={user.id}>
                  <td>{user.email}</td>
                  <td>{user.role}</td>
                  <td>
                    {user.is_active ? "Active" : "Disabled"}
                    {user.must_change_password ? " · must change password" : ""}
                  </td>
                  <td>{user.last_login_at ? formatWhen(user.last_login_at) : "Never"}</td>
                  <td className="admin-row-actions">
                    <button
                      type="button"
                      className="btn ghost"
                      onClick={() =>
                        void run(() =>
                          api
                            .adminUpdateUser(user.id, {
                              role: user.role === "admin" ? "viewer" : "admin",
                            })
                            .then(() => undefined),
                        )
                      }
                    >
                      Make {user.role === "admin" ? "viewer" : "admin"}
                    </button>
                    <button
                      type="button"
                      className="btn ghost"
                      onClick={() =>
                        void run(() =>
                          api
                            .adminUpdateUser(user.id, { is_active: !user.is_active })
                            .then(() => undefined),
                        )
                      }
                    >
                      {user.is_active ? "Disable" : "Enable"}
                    </button>
                    <button
                      type="button"
                      className="btn ghost"
                      onClick={() =>
                        void run(async () => {
                          const reset = await api.adminResetPassword(user.id);
                          setHandover({
                            email: reset.user.email,
                            password: reset.temporary_password,
                          });
                        })
                      }
                    >
                      Reset password
                    </button>
                  </td>
                </tr>
              ))}
            </tbody>
          </table>
        </Panel>
      </div>
    </Section>
  );
}

function InvitesPanel() {
  const { data, error, loading, refresh } = useResource<AdminInvite[]>(() =>
    api.adminInvites(),
  );
  const [role, setRole] = useState<AdminUser["role"]>("viewer");
  const [email, setEmail] = useState("");
  const [link, setLink] = useState("");
  const [actionError, setActionError] = useState("");

  const mint = async (event: React.FormEvent) => {
    event.preventDefault();
    setActionError("");
    try {
      const created = await api.adminCreateInvite(role, email || undefined);
      // The token exists in readable form exactly once -- here.
      setLink(`${window.location.origin}/register?invite=${encodeURIComponent(created.token)}`);
      setEmail("");
      refresh();
    } catch (err) {
      setActionError(err instanceof Error ? err.message : "Could not create the invite");
    }
  };

  return (
    <Section id="admin-invites" title="Invitations">
      <div className="chart-card wide">
        <form className="admin-invite" onSubmit={mint}>
          <input
            type="email"
            placeholder="Bind to an email (optional)"
            value={email}
            onChange={(event) => setEmail(event.target.value)}
          />
          <select
            value={role}
            onChange={(event) => setRole(event.target.value as AdminUser["role"])}
          >
            <option value="viewer">Viewer</option>
            <option value="admin">Admin</option>
          </select>
          <button type="submit" className="btn">
            Create invite link
          </button>
        </form>

        {link ? (
          <p className="admin-handover">
            Send this link — it works once and is shown only now:
            <br />
            <code>{link}</code>
          </p>
        ) : null}
        {actionError ? <p className="auth-error">{actionError}</p> : null}

        <Panel loading={loading} error={error}>
          {(data ?? []).length === 0 ? (
            <p className="empty-chart">No invitations yet.</p>
          ) : (
            <table className="data-table">
              <thead>
                <tr>
                  <th>Created</th>
                  <th>Role</th>
                  <th>For</th>
                  <th>Status</th>
                  <th />
                </tr>
              </thead>
              <tbody>
                {(data ?? []).map((invite) => {
                  const spent =
                    invite.accepted_at ||
                    invite.revoked_at ||
                    new Date(invite.expires_at) < new Date();
                  return (
                    <tr key={invite.id}>
                      <td>{formatWhen(invite.created_at)}</td>
                      <td>{invite.role}</td>
                      <td>{invite.email ?? "Anyone with the link"}</td>
                      <td>{describeInvite(invite)}</td>
                      <td>
                        {spent ? null : (
                          <button
                            type="button"
                            className="btn ghost"
                            onClick={() => void api.adminRevokeInvite(invite.id).then(refresh)}
                          >
                            Revoke
                          </button>
                        )}
                      </td>
                    </tr>
                  );
                })}
              </tbody>
            </table>
          )}
        </Panel>
      </div>
    </Section>
  );
}

function describeInvite(invite: AdminInvite): string {
  if (invite.accepted_at) return `Used ${formatWhen(invite.accepted_at)}`;
  if (invite.revoked_at) return "Revoked";
  if (new Date(invite.expires_at) < new Date()) return "Expired";
  return `Valid until ${formatWhen(invite.expires_at)}`;
}

function SessionsPanel() {
  const { data, error, loading, refresh } = useResource<AdminSession[]>(() =>
    api.adminSessions(),
  );

  return (
    <Section id="admin-sessions" title="Active sessions">
      <div className="chart-card wide">
        <Panel loading={loading} error={error}>
          {(data ?? []).length === 0 ? (
            <p className="empty-chart">No active sessions.</p>
          ) : (
            <table className="data-table">
              <thead>
                <tr>
                  <th>Account</th>
                  <th>Signed in</th>
                  <th>Last seen</th>
                  <th>Address</th>
                  <th />
                </tr>
              </thead>
              <tbody>
                {(data ?? []).map((session) => (
                  <tr key={session.id}>
                    <td>{session.email}</td>
                    <td>{formatWhen(session.created_at)}</td>
                    <td>{formatWhen(session.last_seen_at)}</td>
                    <td>{session.client_ip ?? "—"}</td>
                    <td>
                      <button
                        type="button"
                        className="btn ghost"
                        onClick={() =>
                          void api.adminRevokeSession(session.id).then(refresh)
                        }
                      >
                        Revoke
                      </button>
                    </td>
                  </tr>
                ))}
              </tbody>
            </table>
          )}
        </Panel>
      </div>
    </Section>
  );
}

function AuditPanel() {
  const { data, error, loading } = useResource(() => api.adminAudit(100));

  return (
    <Section id="admin-audit" title="Audit trail">
      <div className="chart-card wide">
        <Panel loading={loading} error={error}>
          <p className="muted">{data?.total ?? 0} recorded events</p>
          <table className="data-table">
            <thead>
              <tr>
                <th>When</th>
                <th>Event</th>
                <th>Account</th>
                <th>Address</th>
                <th>Detail</th>
              </tr>
            </thead>
            <tbody>
              {(data?.entries ?? []).map((entry: AdminAuditEntry) => (
                <tr key={entry.id}>
                  <td>{formatWhen(entry.created_at)}</td>
                  <td>{entry.event}</td>
                  <td>{entry.actor_email ?? "—"}</td>
                  <td>{entry.client_ip ?? "—"}</td>
                  <td>{entry.detail ?? "—"}</td>
                </tr>
              ))}
            </tbody>
          </table>
        </Panel>
      </div>
    </Section>
  );
}

function SystemPanel() {
  const { data, error, loading } = useResource<AdminSystem>(() => api.adminSystem());

  return (
    <Section id="admin-system" title="System">
      <div className="chart-card wide">
        <Panel loading={loading} error={error}>
          {data ? (
            <div className="stat-grid">
              <Stat label="Environment" value={data.environment} />
              <Stat label="WHOOP" value={data.whoop_connected ? "Connected" : "Not connected"} />
              <Stat label="Secure cookies" value={data.secure_cookies ? "On" : "Off"} />
              <Stat label="Session length" value={`${data.session_ttl_minutes} min`} />
              <Stat label="Accounts" value={String(data.accounts.total)} />
              <Stat label="Active admins" value={String(data.accounts.active_admins)} />
              <Stat label="Active sessions" value={String(data.accounts.active_sessions)} />
              <Stat label="Health data" value={formatBytes(data.database.size_bytes)} />
              <Stat label="Auth data" value={formatBytes(data.auth_database.size_bytes)} />
              <Stat
                label="Last recompute"
                value={
                  data.last_recompute
                    ? `${formatWhen(data.last_recompute.at)} · ${data.last_recompute.trigger}`
                    : "Never"
                }
              />
            </div>
          ) : null}
        </Panel>
      </div>
    </Section>
  );
}

function Stat({ label, value }: { label: string; value: string }) {
  return (
    <div className="stat-card">
      <div className="stat-label">{label}</div>
      <div className="stat-value compact">{value}</div>
    </div>
  );
}

function formatWhen(value: string): string {
  const parsed = new Date(value);
  return Number.isNaN(parsed.getTime()) ? value : parsed.toLocaleString();
}

function formatBytes(bytes: number | null): string {
  if (bytes === null) return "—";
  if (bytes < 1024) return `${bytes} B`;
  if (bytes < 1024 * 1024) return `${(bytes / 1024).toFixed(0)} KB`;
  return `${(bytes / (1024 * 1024)).toFixed(1)} MB`;
}
