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
}

export function MobileShell({ tab, onTab, overlay, children }: Props) {
  return (
    <div className="mobile-shell">
      <div className="mobile-body">{overlay ?? children}</div>
      <BottomNav tab={tab} onTab={onTab} />
    </div>
  );
}
