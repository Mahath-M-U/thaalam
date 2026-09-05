import { useState, type FormEvent } from "react";
import { useLocation, useNavigate } from "react-router-dom";
import { useAuth } from "../../auth/AuthContext";
import { PATHS } from "../../routes";
import AuthShell from "./AuthShell";

export default function LoginView() {
  const { signIn } = useAuth();
  const navigate = useNavigate();
  const location = useLocation();

  const [email, setEmail] = useState("");
  const [password, setPassword] = useState("");
  const [error, setError] = useState("");
  const [busy, setBusy] = useState(false);

  const submit = async (event: FormEvent) => {
    event.preventDefault();
    setBusy(true);
    setError("");
    try {
      const user = await signIn(email, password);
      // Finish the trip the guard interrupted, unless a setup password is
      // still in the way.
      const intended = (location.state as { from?: string } | null)?.from;
      navigate(
        user.must_change_password ? PATHS.password : (intended ?? PATHS.dashboard),
        { replace: true },
      );
    } catch (err) {
      // Shown verbatim: the server deliberately returns one message for a
      // wrong password and an unknown account alike.
      setError(err instanceof Error ? err.message : "Could not sign in");
    } finally {
      setBusy(false);
    }
  };

  return (
    <AuthShell>
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
    </AuthShell>
  );
}
