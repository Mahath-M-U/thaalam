import { useState } from "react";
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
import { useDashboardData } from "./hooks/useDashboardData";
import type { SectionId } from "./types";
import { CHART_COLORS } from "./chartTheme";

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

  const name =
    data?.profile.profile.first_name ||
    data?.profile.profile.email ||
    "Athlete";

  return (
    <div className="app">
      <aside className="sidebar">
        <div className="brand">
          <span className="brand-mark">Θ</span>
          <div>
            <strong>Thaalam</strong>
            <small>WHOOP dashboard</small>
          </div>
        </div>

        <nav className="nav">
          {NAV.map((item) => (
            <button
              key={item.id}
              type="button"
              className={section === item.id ? "active" : ""}
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
          <button type="button" className="btn ghost" onClick={() => void reload()}>
            Refresh data
          </button>
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
          {data?.profile.body_measurement.max_heart_rate != null && (
            <div className="pill">
              Max HR {data.profile.body_measurement.max_heart_rate} bpm
            </div>
          )}
        </header>

        {loading && (
          <div className="state-panel">
            <div className="spinner" />
            <p>Loading dashboard…</p>
          </div>
        )}

        {error && !loading && (
          <div className="state-panel error">
            <h2>Could not load data</h2>
            <p>{error}</p>
            <p className="muted">
              Start the API with <code>uv run run_api.py</code>, and sync WHOOP
              data first with <code>uv run main.py</code>.
            </p>
            <button type="button" className="btn" onClick={() => void reload()}>
              Try again
            </button>
          </div>
        )}

        {data && !loading && (
          <>
            <div id="overview">
              <StatCards stats={data.summary.stats} latest={data.summary.latest} />
            </div>

            <InsightsPanel insights={data.insights} />

            <Section id="recovery" title="Recovery" accent={CHART_COLORS.recovery}>
              <RecoveryChart records={data.recovery} />
              <HrvRhrChart records={data.recovery} />
            </Section>

            <Section id="strain" title="Strain" accent={CHART_COLORS.strain}>
              <StrainChart records={data.cycles} />
              <StrainVsRecovery records={data.daily} />
            </Section>

            <Section id="sleep" title="Sleep" accent={CHART_COLORS.sleep}>
              <SleepTrendsChart records={data.sleep} />
              <SleepStagesChart stages={data.sleepStages} />
              <SleepVsRecoveryChart daily={data.daily} insights={data.insights} />
              <SleepDetailTable records={data.sleep} />
            </Section>

            <Section id="workouts" title="Workouts" accent={CHART_COLORS.amber}>
              <WorkoutFrequencyChart workouts={data.workouts} />
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
