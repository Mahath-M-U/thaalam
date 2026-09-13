import { useCallback, useMemo } from "react";
import { useLocation, useNavigate } from "react-router-dom";
import type { TabId } from "./types";

/**
 * The URL is the single source of truth for which screen is showing.
 *
 * Desktop and mobile share one tab set and one path space rather than each
 * keeping its own: a link to /sleep has to open the Sleep tab on whichever
 * surface the recipient happens to be using. Reads and the runway stay
 * addressable too, as overlays opened from inside a tab.
 */

export const TAB_IDS: TabId[] = ["today", "sleep", "load", "rhythm", "whoop"];

/** Which tab an overlay belongs to, so closing one lands somewhere sensible. */
export const TAB_FOR_OVERLAY: { reads: TabId; runway: TabId } = {
  reads: "today",
  runway: "load",
};

export const ADMIN_TABS = ["users", "sessions", "audit", "system"] as const;
export type AdminTab = (typeof ADMIN_TABS)[number];

//: Kept in step with passwords.MIN_PASSWORD_LENGTH on the server, which is
//: the side that actually enforces it.
export const MIN_PASSWORD_LENGTH = 12;

export const PATHS = {
  login: "/login",
  register: "/register",
  password: "/password",
  dashboard: "/",
  reads: "/reads",
  runway: "/runway",
  admin: "/admin",
} as const;

export interface AppRoute {
  tab: TabId;
  openRead: string | null;
  readsOpen: boolean;
  runwayOpen: boolean;
  showAdmin: boolean;
  adminTab: AdminTab;
}

const DEFAULT_ROUTE: AppRoute = {
  tab: "today",
  openRead: null,
  readsOpen: false,
  runwayOpen: false,
  showAdmin: false,
  adminTab: "users",
};

export function parseRoute(pathname: string): AppRoute {
  const [first, second] = pathname.split("/").filter(Boolean);

  if (first === "admin") {
    const adminTab = ADMIN_TABS.find((candidate) => candidate === second);
    return { ...DEFAULT_ROUTE, showAdmin: true, adminTab: adminTab ?? "users" };
  }

  if (first === "reads") {
    return {
      ...DEFAULT_ROUTE,
      tab: TAB_FOR_OVERLAY.reads,
      readsOpen: true,
      openRead: second ? decodeURIComponent(second) : null,
    };
  }

  if (first === "runway") {
    return { ...DEFAULT_ROUTE, tab: TAB_FOR_OVERLAY.runway, runwayOpen: true };
  }

  const tab = TAB_IDS.find((candidate) => candidate === first);
  if (tab) {
    return { ...DEFAULT_ROUTE, tab };
  }

  return DEFAULT_ROUTE;
}

export function pathForTab(tab: TabId): string {
  return tab === "today" ? PATHS.dashboard : `/${tab}`;
}

export function pathForRead(readId: string): string {
  return `${PATHS.reads}/${encodeURIComponent(readId)}`;
}

export function pathForAdminTab(tab: AdminTab): string {
  return tab === "users" ? PATHS.admin : `${PATHS.admin}/${tab}`;
}

/**
 * Route-derived view state with setters shaped like the useState ones they
 * replaced, so callers read the same either way.
 */
export function useAppRoute() {
  const location = useLocation();
  const navigate = useNavigate();
  const route = useMemo(() => parseRoute(location.pathname), [location.pathname]);

  const setTab = useCallback((tab: TabId) => navigate(pathForTab(tab)), [navigate]);

  const setOpenRead = useCallback(
    (readId: string | null) => {
      // Closing a dive goes back to the list it was opened from.
      navigate(readId ? pathForRead(readId) : PATHS.reads);
    },
    [navigate],
  );

  const setReadsOpen = useCallback(
    (open: boolean) => navigate(open ? PATHS.reads : pathForTab(TAB_FOR_OVERLAY.reads)),
    [navigate],
  );

  const setRunwayOpen = useCallback(
    (open: boolean) => navigate(open ? PATHS.runway : pathForTab(TAB_FOR_OVERLAY.runway)),
    [navigate],
  );

  const setShowAdmin = useCallback(
    (open: boolean) => navigate(open ? PATHS.admin : PATHS.dashboard),
    [navigate],
  );

  const setAdminTab = useCallback(
    (tab: AdminTab) => navigate(pathForAdminTab(tab)),
    [navigate],
  );

  return {
    ...route,
    setTab,
    setOpenRead,
    setReadsOpen,
    setRunwayOpen,
    setShowAdmin,
    setAdminTab,
  };
}
