import { StrictMode } from "react";
import { createRoot } from "react-dom/client";
import App from "./App";
import { AuthProvider, useAuth } from "./auth/AuthContext";
import LoginView from "./components/auth/LoginView";
import "./styles.css";

/**
 * Nothing of the dashboard renders until the server confirms a session, and a
 * bootstrap credential is held at the password screen rather than let through.
 */
function Gate() {
  const { status, user } = useAuth();

  if (status === "checking") {
    return (
      <div className="auth-screen">
        <div className="state-panel">
          <span className="spinner" />
          <p>Loading your baseline…</p>
        </div>
      </div>
    );
  }

  if (status === "signed-out" || user?.must_change_password) {
    return <LoginView />;
  }

  return <App />;
}

const root = document.getElementById("root");
if (!root) {
  throw new Error("Root element #root not found");
}

createRoot(root).render(
  <StrictMode>
    <AuthProvider>
      <Gate />
    </AuthProvider>
  </StrictMode>,
);
