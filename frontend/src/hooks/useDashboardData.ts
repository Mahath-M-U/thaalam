import { useCallback, useEffect, useState } from "react";
import { api } from "../api";
import type {
  CycleRecord,
  DailyBriefResponse,
  DailyRecord,
  InsightsResponse,
  ProfileResponse,
  RecoveryRecord,
  SleepRecord,
  SleepStage,
  SportStrain,
  SummaryResponse,
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

export interface DashboardData {
  summary: SummaryResponse;
  profile: ProfileResponse;
  recovery: RecoveryRecord[];
  cycles: CycleRecord[];
  daily: DailyRecord[];
  sleep: SleepRecord[];
  workouts: WorkoutRecord[];
  sleepStages: SleepStage[];
  sports: SportStrain[];
  insights: InsightsResponse;
  dailyBrief: DailyBriefResponse;
  vitality: VitalityResponse;
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
      const [
        summary,
        profile,
        recoveryRes,
        cyclesRes,
        dailyRes,
        sleepRes,
        workoutsRes,
        stagesRes,
        sportsRes,
        insights,
        dailyBrief,
        vitality,
      ] = await Promise.all([
        api.summary(),
        api.profile(),
        api.recovery(),
        api.cycles(),
        api.daily(),
        api.sleep(),
        api.workouts(),
        api.sleepStages(),
        api.workoutsBySport(),
        api.insights(),
        api.dailyBrief(),
        api.vitality().catch(() => EMPTY_VITALITY),
      ]);

      setState({
        loading: false,
        error: null,
        data: {
          summary,
          profile,
          recovery: recoveryRes.records,
          cycles: cyclesRes.records,
          daily: dailyRes.records,
          sleep: sleepRes.records,
          workouts: workoutsRes.records,
          sleepStages: stagesRes.stages,
          sports: sportsRes.sports,
          insights,
          dailyBrief,
          vitality,
        },
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
