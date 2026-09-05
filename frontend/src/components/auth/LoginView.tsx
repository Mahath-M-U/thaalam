import { useState, type FormEvent } from "react";
import { useAuth } from "../../auth/AuthContext";

const MIN_PASSWORD_LENGTH = 12;

/** Sign-in, and the forced rotation a bootstrap credential lands in. */
export default function LoginView() {
  const { status, user, signIn, changePassword } = useAuth();
  const mustRotate = status === "signed-in" && user?.must_change_password;

  return (
    <div className="auth-screen">
      <div className="auth-card">
        <div className="auth-brand">
          <span className="brand-mark">Θ</span>
          <div>
            <strong>Thaalam</strong>
            <small>WHOOP</small>
          </div>
        </div>
        {mustRotate ? (
          <ChangePasswordForm onSubmit={changePassword} />
        ) : (
          <SignInForm onSubmit={signIn} />
        )}
      </div>
    </div>
  );
}

function SignInForm({
  onSubmit,
}: {
  onSubmit: (email: string, password: string) => Promise<void>;
}) {
  const [email, setEmail] = useState("");
  const [password, setPassword] = useState("");
  const [error, setError] = useState("");
  const [busy, setBusy] = useState(false);

  const submit = async (event: FormEvent) => {
    event.preventDefault();
    setBusy(true);
    setError("");
    try {
      await onSubmit(email, password);
    } catch (err) {
      // Shown verbatim: the server deliberately returns one message for a
      // wrong password and an unknown account alike.
      setError(err instanceof Error ? err.message : "Could not sign in");
    } finally {
      setBusy(false);
    }
  };

  return (
    <form className="auth-form" onSubmit={submit}>
      <div className="auth-kicker">Sign in</div>
      <h1>Welcome back</h1>
      <p className="auth-lede">Your data stays where you put it.</p>

      <label htmlFor="auth-email">Email</label>
      <input
        id="auth-email"
        type="email"
        autoComplete="username"
        required
        value={email}
        onChange={(event) => setEmail(event.target.value)}
      />

      <label htmlFor="auth-password">Password</label>
      <input
        id="auth-password"
        type="password"
        autoComplete="current-password"
        required
        value={password}
        onChange={(event) => setPassword(event.target.value)}
      />

      {error ? (
        <p className="auth-error" role="alert">
          {error}
        </p>
      ) : null}

      <button type="submit" className="btn" disabled={busy}>
        {busy ? "Signing in…" : "Sign in"}
      </button>
    </form>
  );
}

function ChangePasswordForm({
  onSubmit,
}: {
  onSubmit: (current: string, next: string) => Promise<void>;
}) {
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
      await onSubmit(current, next);
    } catch (err) {
      setError(err instanceof Error ? err.message : "Could not change password");
    } finally {
      setBusy(false);
    }
  };

  return (
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
  );
}
