import { useEffect, useState, type ReactNode } from "react";
import type { MobileTab } from "../../types";
import { BottomNav } from "./BottomNav";

const MOBILE_QUERY = "(max-width: 959px)";

export function useIsMobile(query = MOBILE_QUERY): boolean {
  const [matches, setMatches] = useState(() =>
    typeof window !== "undefined" ? window.matchMedia(query).matches : false,
  );

  useEffect(() => {
    const media = window.matchMedia(query);
    const update = () => setMatches(media.matches);
    update();
    media.addEventListener("change", update);
    return () => media.removeEventListener("change", update);
  }, [query]);

  return matches;
}

interface Props {
  tab: MobileTab;
  onTab: (tab: MobileTab) => void;
  overlay?: ReactNode;
  children: ReactNode;
  hideNav?: boolean;
  syncError?: string | null;
  onRetry?: () => void;
  syncing?: boolean;
}

export function MobileShell({
  tab,
  onTab,
  overlay,
  children,
  hideNav = false,
  syncError,
  onRetry,
  syncing = false,
}: Props) {
  const hasOverlay = overlay != null;

  useEffect(() => {
    window.scrollTo(0, 0);
  }, [tab, hasOverlay]);

  return (
    <div className="mobile-shell">
      <div className="mobile-body">
        {syncError ? (
          <div className="mobile-sync-error" role="alert">
            <p>{syncError}</p>
            {onRetry ? (
              <button type="button" className="btn" disabled={syncing} onClick={onRetry}>
                {syncing ? "Syncing…" : "Try again"}
              </button>
            ) : null}
          </div>
        ) : null}
        {overlay ?? children}
      </div>
      <BottomNav tab={tab} onTab={onTab} hidden={hideNav} />
    </div>
  );
}
