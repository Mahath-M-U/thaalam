import { useCallback, useEffect, useState } from "react";
import { api } from "../api";
import type {
  CycleRecord,
  DailyRecord,
  InsightsResponse,
  ProfileResponse,
  RecoveryRecord,
  SleepRecord,
  SleepStage,
  SportStrain,
  SummaryResponse,
  WorkoutRecord,
} from "../types";

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
