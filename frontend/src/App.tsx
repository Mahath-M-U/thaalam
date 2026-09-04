import { useCallback, useEffect, useMemo, useState } from "react";
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
import { CardiacEfficiencyDive, CardiacEfficiencyPreview } from "./components/deepDives/CardiacEfficiencyDive";
import { CircadianPhaseDive, CircadianPhasePreview } from "./components/deepDives/CircadianPhaseDive";
import { HyperarousalDive } from "./components/deepDives/HyperarousalDive";
import { StageDependencyDive, StageDependencyPreview } from "./components/deepDives/StageDependencyDive";
import { StrainSensitivityDive, StrainSensitivityPreview } from "./components/deepDives/StrainSensitivityDive";
import { GenericReadDive } from "./components/DeepDive";
import { InsightsPanel } from "./components/InsightsPanel";
import { ReadsTable } from "./components/ReadsTable";
import { RunwayCard } from "./components/RunwayCard";
import { ScoreRingCard } from "./components/ScoreRingCard";
import { RunwayDive } from "./components/deepDives/RunwayDive";
import { Section } from "./components/Section";
import { SleepDetailTable } from "./components/SleepDetailTable";
import { StatCards } from "./components/StatCards";
import { api } from "./api";
import { useDashboardData } from "./hooks/useDashboardData";
import type {
  CardiacSportDive,
  DerivedRead,
  DerivedReadDiveResponse,
  DerivedReadsResponse,
  HyperarousalPoint,
  PhaseCalendarCell,
  PhasePenaltyBar,
  SectionId,
  SportEfficiencyDelta,
  StageVarianceSlice,
  RunwayResponse,
  StrainScatterPoint,
} from "./types";
import {
  DEFAULT_RANGE_DAYS,
  filterByDays,
  RANGE_OPTIONS,
  type RangeDays,
} from "./utils";

const NAV: { id: SectionId | "reads"; label: string }[] = [
  { id: "overview", label: "Overview" },
  { id: "insights", label: "Insights" },
  { id: "recovery", label: "Recovery" },
  { id: "strain", label: "Strain" },
  { id: "sleep", label: "Sleep" },
  { id: "workouts", label: "Workouts" },
  { id: "reads", label: "Reads" },
];

export default function App() {
  const { data, loading, error, reload } = useDashboardData();
  const [section, setSection] = useState<SectionId | "reads">("overview");
  const [rangeDays, setRangeDays] = useState<RangeDays>(DEFAULT_RANGE_DAYS);
  const [syncing, setSyncing] = useState(false);
  const [syncError, setSyncError] = useState<string | null>(null);
  const [readsPayload, setReadsPayload] = useState<DerivedReadsResponse | null>(null);
  const [openRead, setOpenRead] = useState<string | null>(null);
  const [divePayload, setDivePayload] = useState<DerivedReadDiveResponse | null>(null);
  const [diveStatus, setDiveStatus] = useState<"idle" | "loading" | "error">("idle");
  const [runway, setRunway] = useState<RunwayResponse | null>(null);
  const [runwayOpen, setRunwayOpen] = useState(false);

  const loadRunway = useCallback(async () => {
    try {
      setRunway(await api.derivedRunway());
    } catch {
      setRunway(null);
    }
  }, []);

  useEffect(() => {
    if (!data) return;
    void api
      .derivedReads()
      .then(setReadsPayload)
      .catch(() => setReadsPayload(null));
    void loadRunway();
  }, [data, loadRunway]);

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

  const handleRefresh = async () => {
    setSyncing(true);
    setSyncError(null);
    try {
      await api.sync();
      await reload();
      await loadRunway();
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
  const reads = readsPayload?.reads ?? [];
  const readById = (id: string) => reads.find((row) => row.id === id);
  const cardiacPreview = readById("cardiac_efficiency")?.preview as
    | { sports?: SportEfficiencyDelta[] }
    | undefined;
  const efficiencyDeltas = cardiacPreview?.sports ?? [];

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
                setOpenRead(null);
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
            <p className="verdict">
              {data?.vitality?.verdict ||
                "Your vitality score lands here once nights are scored."}
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

        <div className="score-runway-row">
          {data && !loading ? <ScoreRingCard vitality={data.vitality} /> : null}
          <RunwayCard runway={runway} onOpen={() => setRunwayOpen(true)} />
        </div>

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

            {openRead ? (
              divePayload?.read ? (
              <ReadDive
                read={divePayload.read}
                dive={divePayload.dive}
                onBack={() => setOpenRead(null)}
              />
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
            ) : (
              <>
            <InsightsPanel
              insights={data.insights}
              dailyBrief={data.dailyBrief}
              rangeDays={rangeDays}
              onOpenRead={setOpenRead}
            />

            {reads.length > 0 ? (
              <Section id="derived-charts" title="Load and rhythm">
                {readById("cardiac_efficiency") ? (
                  <CardiacEfficiencyPreview
                    read={readById("cardiac_efficiency") as DerivedRead}
                    onOpen={() => setOpenRead("cardiac_efficiency")}
                  />
                ) : null}
                {readById("strain_sensitivity") ? (
                  <StrainSensitivityPreview
                    read={readById("strain_sensitivity") as DerivedRead}
                    onOpen={() => setOpenRead("strain_sensitivity")}
                  />
                ) : null}
                {readById("stage_dependency") ? (
                  <StageDependencyPreview
                    read={readById("stage_dependency") as DerivedRead}
                    onOpen={() => setOpenRead("stage_dependency")}
                  />
                ) : null}
                {readById("circadian_phase") ? (
                  <CircadianPhasePreview
                    read={readById("circadian_phase") as DerivedRead}
                    onOpen={() => setOpenRead("circadian_phase")}
                  />
                ) : null}
              </Section>
            ) : null}

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
              <StrainBySportChart
                sports={data.sports}
                efficiencyDeltas={efficiencyDeltas}
                onOpenRead={setOpenRead}
              />
            </Section>

            {reads.length > 0 ? <ReadsTable reads={reads} onOpen={setOpenRead} /> : null}

            <footer className="page-footer">
              Thaalam · React + FastAPI · data stays on your machine
            </footer>
              </>
            )}
          </>
        )}
      {runwayOpen && runway && (
        <RunwayDive runway={runway} onClose={() => setRunwayOpen(false)} />
      )}
      </main>
    </div>
  );
}


function ReadDive({
  read,
  dive,
  onBack,
}: {
  read: DerivedRead;
  dive: Record<string, unknown>;
  onBack: () => void;
}) {
  if (read.id === "cardiac_efficiency") {
    return (
      <CardiacEfficiencyDive
        read={read}
        dive={dive as { sports?: CardiacSportDive[]; focus?: string; meaning?: string; calibrating?: boolean }}
        onBack={onBack}
      />
    );
  }
  if (read.id === "hyperarousal") {
    return (
      <HyperarousalDive
        read={read}
        dive={dive as { scatter?: HyperarousalPoint[]; meaning?: string; calibrating?: boolean; drivers?: { name: string; count: number; pct: number | null }[] }}
        onBack={onBack}
      />
    );
  }
  if (read.id === "stage_dependency") {
    return (
      <StageDependencyDive
        read={read}
        dive={dive as { variance?: StageVarianceSlice[]; stacked_14?: { date: string; rem: number | null; deep: number | null; light: number | null }[]; meaning?: string | null; calibrating?: boolean; dominant?: string | null }}
        onBack={onBack}
      />
    );
  }
  if (read.id === "strain_sensitivity") {
    return (
      <StrainSensitivityDive
        read={read}
        dive={dive as { scatter?: StrainScatterPoint[]; slope?: number | null; intercept?: number | null; trend_12w?: { date: string; slope: number | null }[]; meaning?: string; calibrating?: boolean }}
        onBack={onBack}
      />
    );
  }
  if (read.id === "circadian_phase") {
    return (
      <CircadianPhaseDive
        read={read}
        dive={dive as { calendar?: PhaseCalendarCell[]; penalty_bars?: PhasePenaltyBar[]; meaning?: string; calibrating?: boolean }}
        onBack={onBack}
      />
    );
  }
  return (
    <GenericReadDive
      read={read}
      meaning={typeof dive.meaning === "string" ? dive.meaning : null}
      onBack={onBack}
    />
  );
}
