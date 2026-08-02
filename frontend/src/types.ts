export interface StatCard {
  label: string;
  value: string;
  accent: string;
}

export interface LatestMetrics {
  cycle_start: string | null;
  recovery_score: number | null;
  strain: number | null;
  hrv_rmssd_milli: number | null;
  resting_heart_rate: number | null;
  sleep_performance_percentage: number | null;
}

export interface SummaryResponse {
  stats: StatCard[];
  latest: LatestMetrics;
}

export interface ProfileResponse {
  profile: {
    user_id?: number;
    email?: string;
    first_name?: string;
    last_name?: string;
    synced_at?: string;
  };
  body_measurement: {
    height_meter?: number;
    weight_kilogram?: number;
    max_heart_rate?: number;
  };
}

export interface RecoveryRecord {
  cycle_id: number;
  cycle_start: string | null;
  recovery_score: number | null;
  resting_heart_rate: number | null;
  hrv_rmssd_milli: number | null;
  spo2_percentage: number | null;
  skin_temp_celsius: number | null;
  score_state: string | null;
}

export interface CycleRecord {
  id: number;
  start: string | null;
  end: string | null;
  strain: number | null;
  average_heart_rate: number | null;
  max_heart_rate: number | null;
  kilojoule: number | null;
  score_state: string | null;
}

export interface DailyRecord {
  cycle_id: number;
  cycle_start: string | null;
  strain: number | null;
  recovery_score: number | null;
  hrv_rmssd_milli: number | null;
  resting_heart_rate: number | null;
  sleep_performance_percentage: number | null;
  sleep_efficiency_percentage: number | null;
  sleep_consistency_percentage: number | null;
}

export interface SleepStageSummary {
  total_in_bed_time_milli?: number;
  total_awake_time_milli?: number;
  total_no_data_time_milli?: number;
  total_light_sleep_time_milli?: number;
  total_slow_wave_sleep_time_milli?: number;
  total_rem_sleep_time_milli?: number;
  sleep_cycle_count?: number;
  disturbance_count?: number;
}

export interface SleepNeeded {
  baseline_milli?: number;
  need_from_sleep_debt_milli?: number;
  need_from_recent_strain_milli?: number;
  need_from_recent_nap_milli?: number;
}

export interface SleepDetail {
  duration_hours: number | null;
  in_bed_hours: number | null;
  asleep_hours: number | null;
  light_hours: number | null;
  deep_hours: number | null;
  rem_hours: number | null;
  awake_hours: number | null;
  awake_minutes: number | null;
  no_data_hours: number | null;
  sleep_cycles: number | null;
  disturbances: number | null;
  need_hours: number | null;
  baseline_need_hours: number | null;
  debt_hours: number | null;
  strain_need_hours: number | null;
  nap_credit_hours: number | null;
  need_gap_hours: number | null;
}

export interface SleepRecord {
  id: string;
  start: string | null;
  end: string | null;
  nap: boolean | null;
  score_state?: string | null;
  sleep_performance_percentage: number | null;
  sleep_efficiency_percentage: number | null;
  sleep_consistency_percentage: number | null;
  respiratory_rate: number | null;
  stage_summary: SleepStageSummary | string | null;
  sleep_needed?: SleepNeeded | string | null;
  detail?: SleepDetail;
}

export interface WorkoutRecord {
  id: string;
  start: string | null;
  sport_name: string | null;
  strain: number | null;
  average_heart_rate: number | null;
  max_heart_rate: number | null;
  kilojoule: number | null;
  distance_meter: number | null;
}

export interface SleepStage {
  stage: string;
  hours: number;
}

export interface SportStrain {
  sport_name: string;
  avg_strain: number;
  count: number;
}

export interface RecordsResponse<T> {
  count: number;
  records: T[];
}

export type SectionId =
  | "overview"
  | "insights"
  | "recovery"
  | "strain"
  | "sleep"
  | "workouts";

export interface InsightCard {
  id: string;
  title: string;
  value: string;
  subtitle: string;
  status: string;
  tone: "positive" | "caution" | "neutral" | string;
  detail: string;
}

export interface InsightsResponse {
  ready: boolean;
  message?: string;
  generated_from_days?: number;
  date_range?: { start: string; end: string };
  cards: InsightCard[];
  sections?: {
    hrv?: {
      series?: { date: string; hrv: number; baseline: number; delta_pct: number }[];
      latest?: { hrv_ms: number; baseline_ms: number; delta_pct: number; status: string };
    };
    training_load?: {
      series?: { date: string; acute_7d: number; chronic_7d_eq: number; acwr: number }[];
      latest?: { acwr: number; status: string };
      bands?: Record<string, string>;
    };
    strain_recovery_lag?: {
      correlation?: number;
      buckets?: { prior_strain: string; avg_next_recovery: number; n: number }[];
    };
    sleep_recovery?: {
      correlation?: number;
      correlation_sleep_efficiency?: number | null;
      correlation_sleep_consistency?: number | null;
      avg_recovery_after_good_sleep?: number | null;
      avg_recovery_after_poor_sleep?: number | null;
      avg_recovery_mid_sleep?: number | null;
      recovery_gap_good_vs_poor?: number | null;
      buckets?: {
        sleep_quality: string;
        avg_recovery: number;
        avg_sleep_performance: number;
        n: number;
      }[];
      scatter?: {
        date: string;
        sleep_performance: number;
        recovery_score: number;
        sleep_efficiency?: number | null;
        sleep_consistency?: number | null;
      }[];
      dual_series?: {
        date: string;
        sleep_performance: number;
        recovery_score: number;
      }[];
      n_pairs?: number;
    };
    recovery_zones?: {
      counts?: { red: number; yellow: number; green: number; total: number };
      percentages?: { red: number; yellow: number; green: number };
    };
    weekday_patterns?: {
      by_weekday?: {
        weekday: string;
        avg_recovery: number | null;
        avg_strain: number | null;
        avg_sleep_performance: number | null;
        n: number;
      }[];
      best_recovery_day?: string | null;
      hardest_strain_day?: string | null;
    };
    sleep_debt?: {
      series?: {
        date: string;
        need_hours: number;
        debt_hours: number;
        in_bed_hours: number | null;
      }[];
      latest?: {
        debt_hours: number;
        need_hours: number;
        gap_hours: number | null;
      };
      avg_debt_14d?: number;
    };
    rolling?: {
      series?: {
        date: string;
        recovery: number | null;
        recovery_7d: number | null;
        strain: number | null;
        strain_7d: number | null;
        hrv: number | null;
        hrv_7d: number | null;
      }[];
    };
    streaks?: {
      current_green_streak?: number;
      best_green_streak?: number;
    };
    training_readiness?: {
      rate_pct?: number;
      poor_recovery_days?: number;
      high_strain_on_poor_days?: number;
    };
  };
  disclaimer?: string;
}
