import { Suspense, lazy, useCallback, useEffect, useMemo, useState, type ReactNode } from "react";
import { useAuth } from "./auth/AuthContext";
import { AdminView } from "./components/admin/AdminView";
import { useAppRoute } from "./routes";
import { AskButton } from "./components/chat/AskButton";
import { ChatDock } from "./components/chat/ChatDock";
import { ChatProvider, useChat } from "./chat/ChatProvider";
import { DailyBriefCard } from "./components/DailyBriefCard";
import { HeadlineScores } from "./components/HeadlineScores";
import { MobileShell, useIsMobile } from "./components/mobile/MobileShell";
import { TodayView } from "./components/mobile/TodayView";
import { ReadsTable } from "./components/ReadsTable";
import { ScoreRingCard } from "./components/ScoreRingCard";
import { WhoopConnectionPanel } from "./components/WhoopConnectionPanel";
import { api } from "./api";
import { EMPTY_VITALITY, useDashboardData, useTabData } from "./hooks/useDashboardData";
import type { DashboardData } from "./hooks/useDashboardData";
import type { ChatPage, DerivedReadDiveResponse, TabId } from "./types";
import {
  DEFAULT_RANGE_DAYS,
  RANGE_OPTIONS,
  type RangeDays,
} from "./utils";

// Chart-heavy tabs load when they are first opened, so recharts stays out of
// the entry bundle and off the critical path of a Today-tab first paint.
const SleepTab = lazy(() => import("./components/tabs/SleepTab"));
const LoadTab = lazy(() => import("./components/tabs/LoadTab"));
const RhythmTab = lazy(() => import("./components/tabs/RhythmTab"));
const WhoopTab = lazy(() => import("./components/tabs/WhoopTab"));

// Deep dives are charts too, and none of them is on screen until something
// is opened.
const ReadDiveView = lazy(() => import("./components/ReadDive"));
const RunwayDive = lazy(() =>
  import("./components/deepDives/RunwayDive").then((m) => ({ default: m.RunwayDive })),
);

/**
 * Wraps a surface in the assistant: the provider that holds the
 * conversation, plus the dock itself rendered above everything.
 *
 * Used by both the mobile and desktop branches below, so the assistant is
 * present on every screen either one can show, with one definition of what
 * "present" means.
 */
function WithChat({
  page,
  readId,
  rangeDays,
  children,
}: {
  page: ChatPage;
  readId: string | null;
  rangeDays: number;
  children: ReactNode;
}) {
  return (
    <ChatProvider page={page} readId={readId} rangeDays={rangeDays}>
      {children}
      <ChatDock />
    </ChatProvider>
  );
}

const NAV: { id: TabId; label: string }[] = [
  { id: "today", label: "Today" },
  { id: "sleep", label: "Sleep" },
  { id: "load", label: "Load" },
  { id: "rhythm", label: "Rhythm" },
  { id: "whoop", label: "From WHOOP" },
];

export default function App() {
  const { data, loading, error, reload } = useDashboardData();
  const { user, isAdmin, signOut } = useAuth();
  const isMobile = useIsMobile();
  // Which screen is showing comes from the URL, so every view is
  // linkable, bookmarkable, and answers to the back button.
  const {
    tab,
    openRead,
    readsOpen,
    runwayOpen,
    showAdmin,
    adminTab,
    setTab,
    setOpenRead,
    setReadsOpen,
    setRunwayOpen,
    setShowAdmin,
    setAdminTab,
  } = useAppRoute();
  const [rangeDays, setRangeDays] = useState<RangeDays>(DEFAULT_RANGE_DAYS);
  const [syncing, setSyncing] = useState(false);
  const [syncError, setSyncError] = useState<string | null>(null);
  const [divePayload, setDivePayload] = useState<DerivedReadDiveResponse | null>(null);
  const [diveStatus, setDiveStatus] = useState<"idle" | "loading" | "error">("idle");
  const [mobileModalOpen, setMobileModalOpen] = useState(false);
  // Bumped by a manual sync so every tab refetches what it had cached.
  const [reloadToken, setReloadToken] = useState(0);

  const { insights, runway, records, loading: tabLoading } = useTabData(tab, reloadToken);

  useEffect(() => {
    if (!openRead) {
      setDivePayload(null);
      setDiveStatus("idle");
      return;
    }
    let cancelled = false;
    setDiveStatus("loading");
    setDivePayload(null);
    void api
      .derivedReadDive(openRead)
      .then((payload) => {
        if (cancelled) return;
        setDivePayload(payload);
        setDiveStatus(payload.present && payload.read ? "idle" : "error");
      })
      .catch(() => {
        if (cancelled) return;
        setDivePayload(null);
        setDiveStatus("error");
      });
    return () => {
      cancelled = true;
    };
  }, [openRead]);

  const handleRefresh = useCallback(async () => {
    setSyncing(true);
    setSyncError(null);
    try {
      await api.sync();
      await reload();
      setReloadToken((n) => n + 1);
    } catch (err) {
      setSyncError(err instanceof Error ? err.message : String(err));
    } finally {
      setSyncing(false);
    }
  }, [reload]);

  const displayError = syncError || error;

  // Ground truth for whichever error the dashboard is showing: a 404 "no
  // database" on first load and a 409 "not connected" from a failed sync
  // are the same underlying fact (no WHOOP token stored yet), so ask the
  // server rather than parse either error's detail text. Admin-only
  // route -- a viewer can't know this and doesn't need to; they're told to
  // ask an admin instead. Re-runs on every new error, which is what lets
  // "Check again" (after actually connecting) resolve to true.
  const [whoopConnected, setWhoopConnected] = useState<boolean | null>(null);
  useEffect(() => {
    if (!displayError || !isAdmin) {
      setWhoopConnected(null);
      return;
    }
    let cancelled = false;
    api
      .whoopStatus()
      .then((res) => {
        if (!cancelled) setWhoopConnected(res.connected);
      })
      .catch(() => {
        if (!cancelled) setWhoopConnected(null);
      });
    return () => {
      cancelled = true;
    };
  }, [displayError, isAdmin]);

  const name =
    data?.profile.profile.first_name ||
    data?.profile.profile.email ||
    "Athlete";

  const reads = data?.reads ?? [];
  const nightCount = data?.headline?.nights ?? 0;

  // Which page the assistant should answer from. Derived from the same route
  // state that decides what is rendered, so the two can never disagree --
  // the most specific thing on screen wins, since that is what a question
  // asked there is about.
  const chatPage: ChatPage = useMemo(() => {
    if (showAdmin) return "admin";
    if (openRead) return "read";
    if (readsOpen) return "reads";
    if (runwayOpen) return "runway";
    return tab;
  }, [showAdmin, openRead, readsOpen, runwayOpen, tab]);

  const readDive = openRead ? (
    divePayload?.read ? (
      <Suspense fallback={<div className="state-panel"><div className="spinner" /><p>Loading…</p></div>}>
        <ReadDiveView
          read={divePayload.read}
          dive={divePayload.dive}
          onBack={() => setOpenRead(null)}
        />
      </Suspense>
    ) : diveStatus === "error" ? (
      <div className="state-panel error">
        <button type="button" className="deep-dive-back" onClick={() => setOpenRead(null)}>
          ← Back
        </button>
        <h2>Could not load this read</h2>
        <p>That deep dive is not available yet. Try again after a refresh, or pick another read.</p>
      </div>
    ) : (
      <div className="state-panel">
        <button type="button" className="deep-dive-back" onClick={() => setOpenRead(null)}>
          ← Back
        </button>
        <div className="spinner" />
        <p>Loading your baseline…</p>
      </div>
    )
  ) : null;

  const openTab = (next: TabId) => {
    setTab(next);
    window.scrollTo(0, 0);
  };

  /**
   * The body of whichever tab is showing. Only this tab is mounted: the
   * others are neither rendered nor fetched until they are opened, which is
   * what keeps the dashboard from being every chart in the app at once.
   */
  const tabBody = (() => {
    if (!data) return null;
    if (readsOpen) {
      return reads.length > 0 ? (
        <ReadsTable reads={reads} onOpen={setOpenRead} />
      ) : (
        <p className="today-empty">Calibrating your reads from your own nights.</p>
      );
    }
    switch (tab) {
      case "sleep":
        return <SleepTab reads={reads} insights={insights} onOpenRead={setOpenRead} />;
      case "load":
        return (
          <LoadTab
            reads={reads}
            insights={insights}
            runway={runway}
            onOpenRead={setOpenRead}
            onOpenRunway={() => setRunwayOpen(true)}
          />
        );
      case "rhythm":
        return <RhythmTab reads={reads} insights={insights} onOpenRead={setOpenRead} />;
      case "whoop":
        return (
          <WhoopTab
            summary={data.summary}
            records={records}
            insights={insights}
            reads={reads}
            rangeDays={rangeDays}
            onOpenRead={setOpenRead}
          />
        );
      default:
        return <TodayDesktop data={data} onOpenRead={setOpenRead} onOpenReads={() => setReadsOpen(true)} />;
    }
  })();

  if (isMobile) {
    return (
      <WithChat page={chatPage} readId={openRead} rangeDays={rangeDays}>
      <MobileShell
        tab={tab}
        onTab={openTab}
        overlay={readDive}
        hideNav={mobileModalOpen}
        syncError={data ? syncError : null}
        onRetry={() => void handleRefresh()}
        syncing={syncing}
        whoopConnected={whoopConnected}
        isAdmin={isAdmin}
      >
        {loading && !data ? (
          <div className="state-panel">
            <div className="spinner" />
            <p>Loading your baseline…</p>
          </div>
        ) : displayError && !data ? (
          <div className="state-panel error">
            <h2>{whoopConnected === false ? "Connect your WHOOP" : "Could not load data"}</h2>
            <WhoopConnectionPanel
              connected={whoopConnected}
              isAdmin={isAdmin}
              syncing={syncing}
              detail={displayError}
              onCheckAgain={() => void (syncError ? handleRefresh() : reload())}
            />
          </div>
        ) : tab === "today" && !readsOpen ? (
          <TodayView
            vitality={data?.vitality ?? EMPTY_VITALITY}
            brief={data?.dailyBrief ?? null}
            headline={data?.headline ?? null}
            reads={reads}
            onOpenRead={setOpenRead}
            onOpenTab={openTab}
            onOpenReads={() => setReadsOpen(true)}
            onRefresh={() => void handleRefresh()}
            syncing={syncing}
            syncError={syncError}
            whoopConnected={whoopConnected}
            isAdmin={isAdmin}
            onVitalityOpenChange={setMobileModalOpen}
          />
        ) : (
          <div className="mobile-tab">
            <HeadlineScores headline={data?.headline ?? null} onOpenTab={openTab} compact />
            <TabBody loading={tabLoading}>{tabBody}</TabBody>
          </div>
        )}
        {runwayOpen && runway && (
          <Suspense fallback={null}>
            <RunwayDive runway={runway} onClose={() => setRunwayOpen(false)} />
          </Suspense>
        )}
      </MobileShell>
      </WithChat>
    );
  }

  return (
    <WithChat page={chatPage} readId={openRead} rangeDays={rangeDays}>
    <div className="app">
      <aside className="sidebar">
        <div className="brand">
          <span className="brand-mark">Θ</span>
          <div>
            <strong>Thaalam</strong>
            <small>WHOOP</small>
          </div>
        </div>

        <nav className="nav">
          {NAV.map((item) => (
            <button
              key={item.id}
              type="button"
              className={`${tab === item.id && !readsOpen ? "active" : ""}${item.id === "today" ? " nav-home" : ""}`.trim()}
              onClick={() => openTab(item.id)}
            >
              {item.label}
            </button>
          ))}
        </nav>

        <div className="sidebar-foot">
          {/* Sync is admin-only server-side; don't offer a viewer a 403. */}
          {isAdmin ? (
            <button
              type="button"
              className="btn ghost"
              disabled={syncing}
              onClick={() => void handleRefresh()}
            >
              {syncing ? "Syncing…" : "Refresh data"}
            </button>
          ) : null}
          <div className="baseline-card">
            <div className="baseline-kicker">Your baseline</div>
            <p>
              {nightCount} {nightCount === 1 ? "night" : "nights"} of your own data
            </p>
          </div>
          <div className="sidebar-account">
            <span className="account-email" title={user?.email}>
              {user?.email}
            </span>
            <span className="account-role">{user?.role}</span>
            {isAdmin ? (
              <button
                type="button"
                className="btn ghost"
                onClick={() => setShowAdmin(!showAdmin)}
              >
                {showAdmin ? "Dashboard" : "Administration"}
              </button>
            ) : null}
            <button type="button" className="btn ghost" onClick={() => void signOut()}>
              Sign out
            </button>
          </div>
        </div>
      </aside>

      {showAdmin ? (
        <main className="main">
          <AdminView
            tab={adminTab}
            onTab={setAdminTab}
            onClose={() => setShowAdmin(false)}
          />
        </main>
      ) : (
      <main className="main">
        <header className="topbar">
          <div>
            <h1>Hello, {name}</h1>
            <p className="verdict">
              {data?.vitality?.verdict ||
                "Your vitality score lands here once nights are scored."}
            </p>
          </div>
          <div className="topbar-actions">
            {/* The range chips only drive the raw WHOOP series. */}
            {tab === "whoop" ? (
              <div className="range-chips" role="group" aria-label="Date range">
                {RANGE_OPTIONS.map((days) => (
                  <button
                    key={days}
                    type="button"
                    className={`chip${rangeDays === days ? " active" : ""}`}
                    onClick={() => setRangeDays(days)}
                  >
                    {days}d
                  </button>
                ))}
              </div>
            ) : null}
            {data?.profile.body_measurement.max_heart_rate != null && (
              <div className="pill">
                Max HR {data.profile.body_measurement.max_heart_rate} bpm
              </div>
            )}
            {/* Top-level entry point, so the assistant is one click away from
                the header of whichever tab is showing. */}
            <AskButton
              question="What stands out in my data today, and what should I do about it?"
              label="Ask about this page"
              send
            />
          </div>
        </header>

        {data && !loading ? (
          <HeadlineScores headline={data.headline} onOpenTab={openTab} />
        ) : null}

        {loading && (
          <div className="state-panel">
            <div className="spinner" />
            <p>Loading your baseline…</p>
          </div>
        )}

        {displayError && !loading && (
          <div className="state-panel error">
            <h2>{whoopConnected === false ? "Connect your WHOOP" : "Could not load data"}</h2>
            <WhoopConnectionPanel
              connected={whoopConnected}
              isAdmin={isAdmin}
              syncing={syncing}
              detail={displayError}
              onCheckAgain={() => void (syncError ? handleRefresh() : reload())}
            />
          </div>
        )}

        {data && !loading && (
          readDive ? readDive : (
            <>
              <TabBody loading={tabLoading}>{tabBody}</TabBody>
              <PageFooter />
            </>
          )
        )}
      {runwayOpen && runway && (
        <Suspense fallback={null}>
          <RunwayDive runway={runway} onClose={() => setRunwayOpen(false)} />
        </Suspense>
      )}
      </main>
      )}
    </div>
    </WithChat>
  );
}

/** One spinner for a tab that is still fetching or still downloading. */
function TabBody({ loading, children }: { loading: boolean; children: ReactNode }) {
  const spinner = (
    <div className="state-panel">
      <div className="spinner" />
      <p>Loading…</p>
    </div>
  );
  return (
    <Suspense fallback={spinner}>
      {loading ? spinner : null}
      {children}
    </Suspense>
  );
}

/**
 * The desktop Today tab: the vitality score, today's read, and anything the
 * reads flagged overnight. The three headline scores sit above it, rendered
 * once for every tab.
 */
function TodayDesktop({
  data,
  onOpenRead,
  onOpenReads,
}: {
  data: DashboardData;
  onOpenRead: (id: string) => void;
  onOpenReads: () => void;
}) {
  const flagged = data.reads.filter((read) => read.flagged && !read.calibrating);
  return (
    <>
      <DailyBriefCard brief={data.dailyBrief} />

      <div className="score-runway-row">
        <ScoreRingCard vitality={data.vitality} />
      </div>

      {flagged.length > 0 ? (
        <section className="today-flagged">
          <div className="today-signals-kicker">Flagged last night</div>
          <ul>
            {flagged.map((read) => (
              <li key={read.id}>
                <button type="button" className="flagged-row" onClick={() => onOpenRead(read.id)}>
                  <span className="flagged-mark" aria-hidden="true">
                    !
                  </span>
                  <div>
                    <h3>{read.title}</h3>
                    <p>{read.finding}</p>
                  </div>
                  <span className="read-chevron" aria-hidden="true">
                    ›
                  </span>
                </button>
              </li>
            ))}
          </ul>
        </section>
      ) : null}

      <button type="button" className="btn today-cta" onClick={onOpenReads}>
        See all eleven reads
      </button>
    </>
  );
}

/**
 * The footer's privacy line, which has to tell the truth about the install it
 * is running in. With the assistant off nothing leaves the machine but WHOOP
 * traffic; with it on, asking a question sends that page's metrics to
 * OpenRouter, and the footer says so rather than keeping a claim that has
 * stopped being true.
 */
function PageFooter() {
  const { enabled } = useChat();
  return (
    <footer className="page-footer">
      Thaalam · React + FastAPI ·{" "}
      {enabled
        ? "your data stays on your machine, except the page metrics sent to OpenRouter when you ask the assistant"
        : "data stays on your machine"}
    </footer>
  );
}
