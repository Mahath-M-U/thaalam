import type { ReactNode } from "react";

/** The framing every auth screen shares: brand mark over a single card. */
export default function AuthShell({ children }: { children: ReactNode }) {
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
        {children}
      </div>
    </div>
  );
}
