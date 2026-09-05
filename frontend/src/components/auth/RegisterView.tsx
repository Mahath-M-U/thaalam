import { useEffect, useState, type FormEvent } from "react";
import { Link, useNavigate, useSearchParams } from "react-router-dom";
import { api, type RegistrationStatus } from "../../api";
import { useAuth } from "../../auth/AuthContext";
import { MIN_PASSWORD_LENGTH, PATHS } from "../../routes";
import AuthShell from "./AuthShell";

/**
 * Registration is open in exactly two cases: before any account exists, and
 * with an invite an administrator issued. There is no open signup -- an
 * account here reads the owner's health data.
 */
export default function RegisterView() {
  const { refresh } = useAuth();
  const navigate = useNavigate();
  const [params] = useSearchParams();
  const inviteFromLink = params.get("invite") ?? "";

  const [status, setStatus] = useState<RegistrationStatus | null>(null);
  const [statusError, setStatusError] = useState("");
  const [email, setEmail] = useState("");
  const [password, setPassword] = useState("");
  const [confirm, setConfirm] = useState("");
  const [invite, setInvite] = useState(inviteFromLink);
  const [error, setError] = useState("");
  const [busy, setBusy] = useState(false);

  useEffect(() => {
    api
      .registrationStatus(inviteFromLink || undefined)
      .then(setStatus)
      .catch((err) =>
        setStatusError(err instanceof Error ? err.message : "Could not reach the server"),
      );
  }, [inviteFromLink]);

  const submit = async (event: FormEvent) => {
    event.preventDefault();
    if (password !== confirm) {
      setError("The passwords do not match.");
      return;
    }
    if (password.length < MIN_PASSWORD_LENGTH) {
      setError(`Use at least ${MIN_PASSWORD_LENGTH} characters.`);
      return;
    }
    setBusy(true);
    setError("");
    try {
      await api.register(email, password, invite || undefined);
      // Registration signs you in, so pick the session up before routing.
      await refresh();
      navigate(PATHS.dashboard, { replace: true });
    } catch (err) {
      setError(err instanceof Error ? err.message : "Could not create the account");
    } finally {
      setBusy(false);
    }
  };

  if (statusError) {
    return (
      <AuthShell>
        <div className="auth-form">
          <div className="auth-kicker">Registration</div>
          <h1>Server unreachable</h1>
          <p className="auth-lede">{statusError}</p>
        </div>
      </AuthShell>
    );
  }

  if (!status) {
    return (
      <AuthShell>
        <div className="auth-form">
          <span className="spinner" />
        </div>
      </AuthShell>
    );
  }

  const firstRun = status.first_run;
  const inviteUnusable = !firstRun && Boolean(inviteFromLink) && !status.invite_valid;

  return (
    <AuthShell>
      <form className="auth-form" onSubmit={submit}>
        <div className="auth-kicker">{firstRun ? "Set up" : "Accept invitation"}</div>
        <h1>{firstRun ? "Claim this dashboard" : "Create your account"}</h1>
        <p className="auth-lede">
          {firstRun
            ? "No account exists yet. The first one becomes the administrator, and this window closes as soon as you take it."
            : "Registration here is by invitation. Paste the invite you were sent."}
        </p>

        {inviteUnusable ? (
          <p className="auth-error" role="alert">
            That invitation has already been used, revoked, or has expired. Ask
            for a fresh one.
          </p>
        ) : null}

        {!firstRun ? (
          <>
            <label htmlFor="reg-invite">Invitation code</label>
            <input
              id="reg-invite"
              type="text"
              required
              value={invite}
              onChange={(event) => setInvite(event.target.value)}
            />
          </>
        ) : null}

        <label htmlFor="reg-email">Email</label>
        <input
          id="reg-email"
          type="email"
          autoComplete="username"
          required
          value={email}
          onChange={(event) => setEmail(event.target.value)}
        />

        <label htmlFor="reg-password">Password</label>
        <input
          id="reg-password"
          type="password"
          autoComplete="new-password"
          required
          minLength={MIN_PASSWORD_LENGTH}
          value={password}
          onChange={(event) => setPassword(event.target.value)}
        />

        <label htmlFor="reg-confirm">Confirm password</label>
        <input
          id="reg-confirm"
          type="password"
          autoComplete="new-password"
          required
          value={confirm}
          onChange={(event) => setConfirm(event.target.value)}
        />

        {error ? (
          <p className="auth-error" role="alert">
            {error}
          </p>
        ) : null}

        <button type="submit" className="btn" disabled={busy}>
          {busy ? "Creating…" : firstRun ? "Create owner account" : "Create account"}
        </button>

        <p className="auth-alt">
          Already have an account? <Link to={PATHS.login}>Sign in</Link>
        </p>
      </form>
    </AuthShell>
  );
}
