/**
 * What to show instead of the raw "No WHOOP database found ..." / "WHOOP is
 * not connected" detail text a 404/409 carries. Both errors reduce to the
 * same underlying fact -- no token is stored yet -- which `connected` (from
 * GET /api/oauth/whoop/status) tells us for certain, so the copy here
 * doesn't need to guess from error text. The caller supplies the wrapping
 * element (a full-page panel, an inline banner, a menu), so this only
 * renders the message and the one action that fits the state.
 */

interface Props {
  /** null while the connection check is in flight. */
  connected: boolean | null;
  isAdmin: boolean;
  syncing: boolean;
  onCheckAgain: () => void;
  /**
   * The error that triggered this panel. Shown only when `connected` is
   * true: a token existing but the load still failing means the "first
   * import" story is a guess, not a fact, and a real bug (a broken query,
   * say) must not be swallowed behind reassuring copy.
   */
  detail?: string | null;
}

export function WhoopConnectionPanel({ connected, isAdmin, syncing, onCheckAgain, detail }: Props) {
  if (!isAdmin) {
    return <p>WHOOP isn't connected yet. Ask an admin to connect it from Administration.</p>;
  }

  if (connected === null) {
    return <p>Checking your WHOOP connection…</p>;
  }

  if (connected) {
    return (
      <>
        <p>WHOOP is connected. A first import can take a few minutes for 90 days of history.</p>
        {detail ? <p className="muted">{detail}</p> : null}
        <button type="button" className="btn" disabled={syncing} onClick={onCheckAgain}>
          {syncing ? "Checking…" : "Check again"}
        </button>
      </>
    );
  }

  return (
    <>
      <p>Connect your WHOOP account to start pulling your sleep, recovery and strain data.</p>
      {/* A real link, not a click handler: WHOOP's consent screen has to be a
          top-level navigation for the admin-only /connect route's CSRF story
          to hold (see thaalam/api/routes/oauth.py). */}
      <a className="btn" href="/api/oauth/whoop/connect">
        Connect WHOOP
      </a>
    </>
  );
}
