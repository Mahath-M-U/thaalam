import { useCallback, useEffect, useRef, useState } from "react";
import { api } from "../api";
import type {
  CycleRecord,
  DailyBriefResponse,
  DailyRecord,
  DerivedRead,
  HeadlineResponse,
  InsightsResponse,
  ProfileResponse,
  RecoveryRecord,
  RunwayResponse,
  SleepRecord,
  SleepStage,
  SportStrain,
  SummaryResponse,
  TabId,
  VitalityResponse,
  WorkoutRecord,
} from "../types";

export const EMPTY_VITALITY: VitalityResponse = {
  present: false,
  score: null,
  band: null,
  parts: [],
  trend_30d: [],
  calibrating: true,
  sleep_not_closed: false,
  verdict: "Your vitality score lands here once nights are scored.",
  cause: "",
  delta_14d: null,
  supporting: null,
};

/**
 * What every tab needs, fetched before first paint.
 *
 * Deliberately small: the dashboard used to open twelve requests at once and
 * render every chart in the app behind them. Everything heavier now waits for
 * the tab that actually shows it — see `useTabData` below.
 */
export interface DashboardData {
  summary: SummaryResponse;
  profile: ProfileResponse;
  dailyBrief: DailyBriefResponse;
  vitality: VitalityResponse;
  headline: HeadlineResponse | null;
  reads: DerivedRead[];
}

interface State {
  data: DashboardData | null;
  loading: boolean;
  error: string | null;
}

export function useDashboardData() {
  const [state, setState] = useState<State>({
    data: null,
    loading: true,
    error: null,
  });

  const load = useCallback(async () => {
    setState((s) => ({ ...s, loading: true, error: null }));
    try {
      const [summary, profile, dailyBrief, vitality, headline, reads] = await Promise.all([
        api.summary(),
        api.profile(),
        api.dailyBrief(),
        api.vitality().catch(() => EMPTY_VITALITY),
        api.derivedHeadline().catch(() => null),
        api
          .derivedReads()
          .then((res) => res.reads)
          .catch(() => []),
      ]);

      setState({
        loading: false,
        error: null,
        data: { summary, profile, dailyBrief, vitality, headline, reads },
      });
    } catch (err) {
      setState({
        data: null,
        loading: false,
        error: err instanceof Error ? err.message : String(err),
      });
    }
  }, []);

  useEffect(() => {
    void load();
  }, [load]);

  return { ...state, reload: load };
}

/* -------------------------------------------------------------------------
   Per-tab data
   ------------------------------------------------------------------------- */

/** The raw WHOOP series — only the "From WHOOP" tab renders any of them. */
export interface WhoopRecords {
  recovery: RecoveryRecord[];
  cycles: CycleRecord[];
  daily: DailyRecord[];
  sleep: SleepRecord[];
  workouts: WorkoutRecord[];
  sleepStages: SleepStage[];
  sports: SportStrain[];
}

type ResourceKey = "insights" | "runway" | "whoopRecords";

/**
 * Which resources each tab needs. Today needs nothing beyond the core fetch,
 * which is why it paints immediately; the seven raw-series calls belong to
 * the one tab that shows raw series.
 */
const TAB_RESOURCES: Record<TabId, ResourceKey[]> = {
  today: [],
  sleep: ["insights"],
  load: ["insights", "runway"],
  rhythm: ["insights"],
  whoop: ["insights", "whoopRecords"],
};

async function fetchWhoopRecords(): Promise<WhoopRecords> {
  const [recovery, cycles, daily, sleep, workouts, stages, sports] = await Promise.all([
    api.recovery(),
    api.cycles(),
    api.daily(),
    api.sleep(),
    api.workouts(),
    api.sleepStages(),
    api.workoutsBySport(),
  ]);
  return {
    recovery: recovery.records,
    cycles: cycles.records,
    daily: daily.records,
    sleep: sleep.records,
    workouts: workouts.records,
    sleepStages: stages.stages,
    sports: sports.sports,
  };
}

const FETCHERS: Record<ResourceKey, () => Promise<unknown>> = {
  insights: () => api.insights(),
  runway: () => api.derivedRunway(),
  whoopRecords: fetchWhoopRecords,
};

interface TabData {
  insights: InsightsResponse | null;
  runway: RunwayResponse | null;
  records: WhoopRecords | null;
  loading: boolean;
}

/**
 * Fetch a tab's resources the first time that tab is opened, once each.
 *
 * The cache is keyed by resource rather than by tab, so the insights payload
 * three tabs share is fetched once however the user moves between them.
 * `reloadToken` changing (a manual sync) clears it so the next tab visit
 * refetches rather than serving what the sync just replaced.
 */
export function useTabData(tab: TabId, reloadToken = 0): TabData {
  const cache = useRef(new Map<ResourceKey, unknown>());
  const inFlight = useRef(new Map<ResourceKey, Promise<unknown>>());
  const [, bump] = useState(0);
  const [loading, setLoading] = useState(false);
  const lastToken = useRef(reloadToken);

  if (lastToken.current !== reloadToken) {
    lastToken.current = reloadToken;
    cache.current.clear();
    inFlight.current.clear();
  }

  useEffect(() => {
    const needed = TAB_RESOURCES[tab].filter((key) => !cache.current.has(key));
    if (needed.length === 0) {
      setLoading(false);
      return;
    }
    let cancelled = false;
    setLoading(true);
    const pending = needed.map((key) => {
      const existing = inFlight.current.get(key);
      const promise =
        existing ??
        FETCHERS[key]()
          .then((value) => {
            cache.current.set(key, value);
            return value;
          })
          // A tab that cannot load its data renders its empty state rather
          // than taking the whole dashboard down with it.
          .catch(() => {
            cache.current.set(key, null);
            return null;
          })
          .finally(() => inFlight.current.delete(key));
      inFlight.current.set(key, promise);
      return promise;
    });
    void Promise.all(pending).then(() => {
      if (cancelled) return;
      setLoading(false);
      bump((n) => n + 1);
    });
    return () => {
      cancelled = true;
    };
  }, [tab, reloadToken]);

  return {
    insights: (cache.current.get("insights") as InsightsResponse | null) ?? null,
    runway: (cache.current.get("runway") as RunwayResponse | null) ?? null,
    records: (cache.current.get("whoopRecords") as WhoopRecords | null) ?? null,
    loading,
  };
}
