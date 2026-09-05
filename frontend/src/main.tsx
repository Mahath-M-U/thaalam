import { StrictMode, type ReactNode } from "react";
import { createRoot } from "react-dom/client";
import { BrowserRouter, Navigate, Route, Routes, useLocation } from "react-router-dom";
import App from "./App";
import { AuthProvider, useAuth } from "./auth/AuthContext";
import ChangePasswordView from "./components/auth/ChangePasswordView";
import LoginView from "./components/auth/LoginView";
import RegisterView from "./components/auth/RegisterView";
import { PATHS } from "./routes";
import "./styles.css";

function Loading() {
  return (
    <div className="auth-screen">
      <div className="state-panel">
        <span className="spinner" />
        <p>Loading your baseline…</p>
      </div>
    </div>
  );
}

/**
 * Nothing of the dashboard renders until the server confirms a session, and an
 * account still on its setup password is held at the password screen.
 */
function RequireAuth({ children }: { children: ReactNode }) {
  const { status, user } = useAuth();
  const location = useLocation();

  if (status === "checking") return <Loading />;

  if (status === "signed-out") {
    // Remember where they were headed so sign-in can finish the trip.
    return <Navigate to={PATHS.login} state={{ from: location.pathname }} replace />;
  }

  if (user?.must_change_password) {
    return <Navigate to={PATHS.password} replace />;
  }

  return <>{children}</>;
}

/** Signed-in users have no business on the sign-in or registration screens. */
function RedirectIfSignedIn({ children }: { children: ReactNode }) {
  const { status, user } = useAuth();

  if (status === "checking") return <Loading />;
  if (status === "signed-in") {
    return <Navigate to={user?.must_change_password ? PATHS.password : PATHS.dashboard} replace />;
  }
  return <>{children}</>;
}

function PasswordRoute() {
  const { status, user } = useAuth();

  if (status === "checking") return <Loading />;
  if (status === "signed-out") return <Navigate to={PATHS.login} replace />;
  // Reached once the password is rotated, or by a user who never needed to.
  if (!user?.must_change_password) return <Navigate to={PATHS.dashboard} replace />;
  return <ChangePasswordView />;
}

const root = document.getElementById("root");
if (!root) {
  throw new Error("Root element #root not found");
}

createRoot(root).render(
  <StrictMode>
    <BrowserRouter>
      <AuthProvider>
        <Routes>
          <Route
            path={PATHS.login}
            element={
              <RedirectIfSignedIn>
                <LoginView />
              </RedirectIfSignedIn>
            }
          />
          <Route
            path={PATHS.register}
            element={
              <RedirectIfSignedIn>
                <RegisterView />
              </RedirectIfSignedIn>
            }
          />
          <Route path={PATHS.password} element={<PasswordRoute />} />
          <Route
            path="/*"
            element={
              <RequireAuth>
                <App />
              </RequireAuth>
            }
          />
        </Routes>
      </AuthProvider>
    </BrowserRouter>
  </StrictMode>,
);
