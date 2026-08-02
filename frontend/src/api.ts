import type {
  BriefExplainerResponse,
  CycleRecord,
  DailyBriefResponse,
  DailyRecord,
  InsightsResponse,
  ProfileResponse,
  RecordsResponse,
  RecoveryRecord,
  SleepRecord,
  SleepStage,
  SportStrain,
  SummaryResponse,
  WorkoutRecord,
} from "./types";

async function getJson<T>(path: string): Promise<T> {
  const res = await fetch(path);
  if (!res.ok) {
    let detail = res.statusText;
    try {
      const body = await res.json();
      detail = body.detail ?? JSON.stringify(body);
    } catch {
      /* ignore parse errors */
    }
    throw new Error(typeof detail === "string" ? detail : JSON.stringify(detail));
  }
  return res.json() as Promise<T>;
}

export const api = {
  health: () => getJson<{ status: string; database_exists: boolean }>("/health"),
  summary: () => getJson<SummaryResponse>("/api/summary"),
  profile: () => getJson<ProfileResponse>("/api/profile"),
  recovery: () => getJson<RecordsResponse<RecoveryRecord>>("/api/recovery"),
  cycles: () => getJson<RecordsResponse<CycleRecord>>("/api/cycles"),
  daily: () => getJson<RecordsResponse<DailyRecord>>("/api/daily"),
  sleep: () => getJson<RecordsResponse<SleepRecord>>("/api/sleep"),
  workouts: () => getJson<RecordsResponse<WorkoutRecord>>("/api/workouts"),
  sleepStages: () => getJson<{ stages: SleepStage[]; nights?: number }>("/api/sleep/stages/average"),
  workoutsBySport: () => getJson<{ sports: SportStrain[] }>("/api/workouts/by-sport"),
  insights: () => getJson<InsightsResponse>("/api/insights"),
  dailyBrief: () => getJson<DailyBriefResponse>("/api/brief"),
  briefExplain: (question: string) =>
    getJson<BriefExplainerResponse>(`/api/brief/explain?question=${encodeURIComponent(question)}`),
};
