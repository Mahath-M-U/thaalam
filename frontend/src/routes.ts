import { useCallback, useMemo } from "react";
import { useLocation, useNavigate } from "react-router-dom";
import type { MobileTab, SectionId } from "./types";

/**
 * The URL is the single source of truth for which screen is showing.
 *
 * Desktop sections and mobile tabs share one path space rather than each
 * keeping its own: a link to /reads has to open the reads screen on whichever
 * surface the recipient happens to be using.
 */

export const SECTION_IDS: SectionId[] = [
  "overview",
  "insights",
  "recovery",
  "strain",
  "sleep",
  "workouts",
];

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
  section: SectionId | "reads";
  mobileTab: MobileTab;
  openRead: string | null;
  runwayOpen: boolean;
  showAdmin: boolean;
  adminTab: AdminTab;
}

const DEFAULT_ROUTE: AppRoute = {
  section: "overview",
  mobileTab: "today",
  openRead: null,
  runwayOpen: false,
  showAdmin: false,
  adminTab: "users",
};

export function parseRoute(pathname: string): AppRoute {
  const [first, second] = pathname.split("/").filter(Boolean);

  if (first === "admin") {
    const tab = ADMIN_TABS.find((candidate) => candidate === second);
    return { ...DEFAULT_ROUTE, showAdmin: true, adminTab: tab ?? "users" };
  }

  if (first === "reads") {
    return {
      ...DEFAULT_ROUTE,
      section: "reads",
      mobileTab: "reads",
      openRead: second ? decodeURIComponent(second) : null,
    };
  }

  if (first === "runway") {
    return { ...DEFAULT_ROUTE, mobileTab: "runway", runwayOpen: true };
  }

  const section = SECTION_IDS.find((candidate) => candidate === first);
  if (section) {
    return { ...DEFAULT_ROUTE, section };
  }

  return DEFAULT_ROUTE;
}

export function pathForSection(section: SectionId | "reads"): string {
  if (section === "reads") return PATHS.reads;
  return section === "overview" ? PATHS.dashboard : `/${section}`;
}

export function pathForMobileTab(tab: MobileTab): string {
  if (tab === "reads") return PATHS.reads;
  if (tab === "runway") return PATHS.runway;
  return PATHS.dashboard;
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

  const setSection = useCallback(
    (section: SectionId | "reads") => navigate(pathForSection(section)),
    [navigate],
  );

  const setMobileTab = useCallback(
    (tab: MobileTab) => navigate(pathForMobileTab(tab)),
    [navigate],
  );

  const setOpenRead = useCallback(
    (readId: string | null) => {
      // Closing a dive goes back to the list it was opened from.
      navigate(readId ? pathForRead(readId) : PATHS.reads);
    },
    [navigate],
  );

  const setRunwayOpen = useCallback(
    (open: boolean) => navigate(open ? PATHS.runway : PATHS.dashboard),
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
    setSection,
    setMobileTab,
    setOpenRead,
    setRunwayOpen,
    setShowAdmin,
    setAdminTab,
  };
}
