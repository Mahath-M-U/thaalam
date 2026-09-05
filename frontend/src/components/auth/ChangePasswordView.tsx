import { useState, type FormEvent } from "react";
import { useNavigate } from "react-router-dom";
import { useAuth } from "../../auth/AuthContext";
import { MIN_PASSWORD_LENGTH, PATHS } from "../../routes";
import AuthShell from "./AuthShell";

/** The forced rotation an invited or reset account lands in. */
export default function ChangePasswordView() {
  const { changePassword } = useAuth();
  const navigate = useNavigate();

  const [current, setCurrent] = useState("");
  const [next, setNext] = useState("");
  const [confirm, setConfirm] = useState("");
  const [error, setError] = useState("");
  const [busy, setBusy] = useState(false);

  const submit = async (event: FormEvent) => {
    event.preventDefault();
    if (next !== confirm) {
      setError("The new passwords do not match.");
      return;
    }
    if (next.length < MIN_PASSWORD_LENGTH) {
      setError(`Use at least ${MIN_PASSWORD_LENGTH} characters.`);
      return;
    }
    setBusy(true);
    setError("");
    try {
      await changePassword(current, next);
      navigate(PATHS.dashboard, { replace: true });
    } catch (err) {
      setError(err instanceof Error ? err.message : "Could not change password");
    } finally {
      setBusy(false);
    }
  };

  return (
    <AuthShell>
      <form className="auth-form" onSubmit={submit}>
        <div className="auth-kicker">Choose a password</div>
        <h1>One more step</h1>
        <p className="auth-lede">
          This account is still on its setup password. Pick your own before you
          carry on.
        </p>

        <label htmlFor="auth-current">Current password</label>
        <input
          id="auth-current"
          type="password"
          autoComplete="current-password"
          required
          value={current}
          onChange={(event) => setCurrent(event.target.value)}
        />

        <label htmlFor="auth-next">New password</label>
        <input
          id="auth-next"
          type="password"
          autoComplete="new-password"
          required
          minLength={MIN_PASSWORD_LENGTH}
          value={next}
          onChange={(event) => setNext(event.target.value)}
        />

        <label htmlFor="auth-confirm">Confirm new password</label>
        <input
          id="auth-confirm"
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
          {busy ? "Saving…" : "Save password"}
        </button>
      </form>
    </AuthShell>
  );
}
