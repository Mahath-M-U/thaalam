import type {
  BriefExplainerResponse,
  CycleRecord,
  DailyBriefResponse,
  DailyRecord,
  DerivedReadDiveResponse,
  DerivedReadsResponse,
  DerivedRunwayResponse,
  InsightsResponse,
  ProfileResponse,
  RecordsResponse,
  RecoveryRecord,
  SleepRecord,
  SleepStage,
  SportStrain,
  SummaryResponse,
  VitalityResponse,
  WorkoutRecord,
} from "./types";

async function requestJson<T>(path: string, init?: RequestInit): Promise<T> {
  const res = await fetch(path, init);
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
  health: () => requestJson<{ status: string; database_exists: boolean }>("/health"),
  summary: () => requestJson<SummaryResponse>("/api/summary"),
  profile: () => requestJson<ProfileResponse>("/api/profile"),
  recovery: () => requestJson<RecordsResponse<RecoveryRecord>>("/api/recovery"),
  cycles: () => requestJson<RecordsResponse<CycleRecord>>("/api/cycles"),
  daily: () => requestJson<RecordsResponse<DailyRecord>>("/api/daily"),
  sleep: () => requestJson<RecordsResponse<SleepRecord>>("/api/sleep"),
  workouts: () => requestJson<RecordsResponse<WorkoutRecord>>("/api/workouts"),
  sleepStages: () => requestJson<{ stages: SleepStage[]; nights?: number }>("/api/sleep/stages/average"),
  workoutsBySport: () => requestJson<{ sports: SportStrain[] }>("/api/workouts/by-sport"),
  insights: () => requestJson<InsightsResponse>("/api/insights"),
  dailyBrief: () => requestJson<DailyBriefResponse>("/api/brief"),
  briefExplain: (question: string) =>
    requestJson<BriefExplainerResponse>(`/api/brief/explain?question=${encodeURIComponent(question)}`),
  sync: () => requestJson<{ ok: boolean }>("/api/sync", { method: "POST" }),
  vitality: () => requestJson<VitalityResponse>("/api/derived/vitality"),
  derivedReads: () => requestJson<DerivedReadsResponse>("/api/derived/reads"),
  derivedReadDive: (id: string) =>
    requestJson<DerivedReadDiveResponse>(`/api/derived/reads/${encodeURIComponent(id)}`),
  derivedRunway: () => requestJson<DerivedRunwayResponse>("/api/derived/runway"),
};
