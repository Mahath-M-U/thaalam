import { useMemo, useState } from "react";
import { HrvRhrChart } from "./components/charts/HrvRhrChart";
import { RecoveryChart } from "./components/charts/RecoveryChart";
import { SleepStagesChart } from "./components/charts/SleepStagesChart";
import { SleepTrendsChart } from "./components/charts/SleepTrendsChart";
import { SleepVsRecoveryChart } from "./components/charts/SleepVsRecoveryChart";
import { StrainChart } from "./components/charts/StrainChart";
import { StrainVsRecovery } from "./components/charts/StrainVsRecovery";
import {
  StrainBySportChart,
  WorkoutFrequencyChart,
} from "./components/charts/WorkoutCharts";
import { InsightsPanel } from "./components/InsightsPanel";
import { Section } from "./components/Section";
import { SleepDetailTable } from "./components/SleepDetailTable";
import { StatCards } from "./components/StatCards";
import { api } from "./api";
import { useDashboardData } from "./hooks/useDashboardData";
import type { SectionId } from "./types";
import {
  DEFAULT_RANGE_DAYS,
  filterByDays,
  RANGE_OPTIONS,
  type RangeDays,
} from "./utils";

const NAV: { id: SectionId; label: string }[] = [
  { id: "overview", label: "Overview" },
  { id: "insights", label: "Insights" },
  { id: "recovery", label: "Recovery" },
  { id: "strain", label: "Strain" },
  { id: "sleep", label: "Sleep" },
  { id: "workouts", label: "Workouts" },
];

export default function App() {
  const { data, loading, error, reload } = useDashboardData();
  const [section, setSection] = useState<SectionId>("overview");
  const [rangeDays, setRangeDays] = useState<RangeDays>(DEFAULT_RANGE_DAYS);
  const [syncing, setSyncing] = useState(false);
  const [syncError, setSyncError] = useState<string | null>(null);

  const handleRefresh = async () => {
    setSyncing(true);
    setSyncError(null);
    try {
      await api.sync();
      await reload();
    } catch (err) {
      setSyncError(err instanceof Error ? err.message : String(err));
    } finally {
      setSyncing(false);
    }
  };

  const displayError = syncError || error;

  const name =
    data?.profile.profile.first_name ||
    data?.profile.profile.email ||
    "Athlete";

  const recovery = useMemo(
    () => (data ? filterByDays(data.recovery, (r) => r.cycle_start, rangeDays) : []),
    [data, rangeDays],
  );
  const cycles = useMemo(
    () => (data ? filterByDays(data.cycles, (r) => r.start, rangeDays) : []),
    [data, rangeDays],
  );
  const daily = useMemo(
    () => (data ? filterByDays(data.daily, (r) => r.cycle_start, rangeDays) : []),
    [data, rangeDays],
  );
  const sleep = useMemo(
    () => (data ? filterByDays(data.sleep, (r) => r.start, rangeDays) : []),
    [data, rangeDays],
  );
  const workouts = useMemo(
    () => (data ? filterByDays(data.workouts, (r) => r.start, rangeDays) : []),
    [data, rangeDays],
  );

  const nightCount = data?.sleep.filter((s) => !s.nap).length ?? 0;
  const sessionCount = data?.workouts.length ?? 0;

  return (
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
              className={`${section === item.id ? "active" : ""}${item.id === "overview" ? " nav-home" : ""}`.trim()}
              onClick={() => {
                setSection(item.id);
                document.getElementById(item.id)?.scrollIntoView({ behavior: "smooth" });
              }}
            >
              {item.label}
            </button>
          ))}
        </nav>

        <div className="sidebar-foot">
          <button
            type="button"
            className="btn ghost"
            disabled={syncing}
            onClick={() => void handleRefresh()}
          >
            {syncing ? "Syncing…" : "Refresh data"}
          </button>
          <div className="baseline-card">
            <div className="baseline-kicker">Your baseline</div>
            <p>
              {nightCount} {nightCount === 1 ? "night" : "nights"} and {sessionCount}{" "}
              {sessionCount === 1 ? "session" : "sessions"} of your own data
            </p>
          </div>
          <p className="muted">
            API on <code>:8000</code>
            <br />
            Sync with <code>uv run main.py</code>
          </p>
        </div>
      </aside>

      <main className="main">
        <header className="topbar">
          <div>
            <h1>Hello, {name}</h1>
            <p className="muted">
              Local WHOOP metrics from DuckDB — interactive charts over your
              synced history.
            </p>
          </div>
          <div className="topbar-actions">
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
            {data?.profile.body_measurement.max_heart_rate != null && (
              <div className="pill">
                Max HR {data.profile.body_measurement.max_heart_rate} bpm
              </div>
            )}
          </div>
        </header>

        {loading && (
          <div className="state-panel">
            <div className="spinner" />
            <p>Loading your baseline…</p>
          </div>
        )}

        {displayError && !loading && (
          <div className="state-panel error">
            <h2>{syncError ? "Could not refresh WHOOP data" : "Could not load data"}</h2>
            <p>{displayError}</p>
            <p className="muted">
              Start the API with <code>uv run run_api.py</code>, connect at{" "}
              <code>/api/oauth/whoop/connect</code>, or run{" "}
              <code>uv run main.py</code>.
            </p>
            <button
              type="button"
              className="btn"
              onClick={() => void (syncError ? handleRefresh() : reload())}
            >
              Try again
            </button>
          </div>
        )}

        {data && !loading && (
          <>
            <div id="overview">
              <StatCards stats={data.summary.stats} latest={data.summary.latest} />
            </div>

            <InsightsPanel
              insights={data.insights}
              dailyBrief={data.dailyBrief}
              rangeDays={rangeDays}
            />

            <Section id="recovery" title="Recovery">
              <RecoveryChart records={recovery} />
              <HrvRhrChart records={recovery} />
            </Section>

            <Section id="strain" title="Strain">
              <StrainChart records={cycles} />
              <StrainVsRecovery records={daily} />
            </Section>

            <Section id="sleep" title="Sleep">
              <SleepTrendsChart records={sleep} />
              <SleepStagesChart stages={data.sleepStages} />
              <SleepVsRecoveryChart
                daily={daily}
                insights={data.insights}
                rangeDays={rangeDays}
              />
              <SleepDetailTable records={sleep} />
            </Section>

            <Section id="workouts" title="Workouts">
              <WorkoutFrequencyChart workouts={workouts} />
              <StrainBySportChart sports={data.sports} />
            </Section>

            <footer className="page-footer">
              Thaalam · React + FastAPI · data stays on your machine
            </footer>
          </>
        )}
      </main>
    </div>
  );
}
