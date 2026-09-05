import {
  Bar,
  BarChart,
  CartesianGrid,
  ResponsiveContainer,
  Tooltip,
  XAxis,
  YAxis,
} from "recharts";
import type { SportEfficiencyDelta, SportStrain, WorkoutRecord } from "../../types";
import { shortDate } from "../../utils";
import { ChartCard } from "../ChartCard";
import { CHART_COLORS, axisLine, axisTick, gridStroke, tooltipStyle } from "../../chartTheme";

interface SportProps {
  sports: SportStrain[];
  efficiencyDeltas?: SportEfficiencyDelta[];
  onOpenRead?: (id: string) => void;
}

export function StrainBySportChart({ sports, efficiencyDeltas, onOpenRead }: SportProps) {
  const deltas = new Map((efficiencyDeltas ?? []).map((d) => [d.sport_name.toLowerCase(), d]));
  const data = [...sports].reverse().map((sport) => {
    const delta = deltas.get(sport.sport_name.toLowerCase());
    return {
      ...sport,
      efficiency_delta_bpm: delta?.enabled ? delta.delta_bpm : null,
    };
  });

  if (data.length === 0) {
    return (
      <ChartCard title="Average strain by sport">
        <p className="empty-chart">No scored workout data yet</p>
      </ChartCard>
    );
  }

  return (
    <ChartCard
      title="Average strain by sport"
      description="Mean workout strain grouped by activity type, with matched-load heart-rate drift where you have enough sessions."
    >
      <ResponsiveContainer width="100%" height={Math.max(220, data.length * 28)}>
        <BarChart
          data={data}
          layout="vertical"
          margin={{ top: 4, right: 16, left: 8, bottom: 4 }}
        >
          <CartesianGrid strokeDasharray="3 3" stroke={gridStroke} horizontal={false} />
          <XAxis
            type="number"
            tick={axisTick}
            axisLine={axisLine}
            tickLine={false}
          />
          <YAxis
            type="category"
            dataKey="sport_name"
            width={100}
            tick={axisTick}
            axisLine={false}
            tickLine={false}
          />
          <Tooltip contentStyle={tooltipStyle} />
          <Bar dataKey="avg_strain" name="Avg strain" fill={CHART_COLORS.ink} radius={[0, 4, 4, 0]} />
        </BarChart>
      </ResponsiveContainer>
      {efficiencyDeltas && efficiencyDeltas.some((d) => d.enabled && d.delta_bpm != null) ? (
        <ul className="sport-efficiency">
          {efficiencyDeltas
            .filter((d) => d.enabled && d.delta_bpm != null)
            .map((d) => (
              <li key={d.sport_name}>
                <button
                  type="button"
                  className="linkish"
                  onClick={() => onOpenRead?.("cardiac_efficiency")}
                >
                  {d.sport_name}
                  <span>
                    {d.delta_bpm != null && d.delta_bpm > 0 ? "+" : ""}
                    {d.delta_bpm?.toFixed(0)} bpm
                  </span>
                </button>
              </li>
            ))}
        </ul>
      ) : null}
      <p className="chart-footnote">
        Efficiency delta is average heart rate drift on sessions within ±8% of that sport's own median
        kilojoule load, versus your earlier matched sessions.
      </p>
    </ChartCard>
  );
}

interface FreqProps {
  workouts: WorkoutRecord[];
}

export function WorkoutFrequencyChart({ workouts }: FreqProps) {
  const byWeek = new Map<string, { week: string; label: string; count: number }>();

  for (const w of workouts) {
    if (!w.start) continue;
    const d = new Date(w.start);
    if (Number.isNaN(d.getTime())) continue;
    // ISO week start (Monday)
    const day = d.getUTCDay();
    const diff = (day + 6) % 7;
    const monday = new Date(d);
    monday.setUTCDate(d.getUTCDate() - diff);
    monday.setUTCHours(0, 0, 0, 0);
    const key = monday.toISOString().slice(0, 10);
    const existing = byWeek.get(key);
    if (existing) {
      existing.count += 1;
    } else {
      byWeek.set(key, { week: key, label: shortDate(key), count: 1 });
    }
  }

  const data = [...byWeek.values()].sort((a, b) => a.week.localeCompare(b.week));

  if (data.length === 0) {
    return (
      <ChartCard title="Workout frequency" wide>
        <p className="empty-chart">No workout data yet</p>
      </ChartCard>
    );
  }

  return (
    <ChartCard
      title="Workout frequency over time"
      description="Number of workouts logged per week."
      wide
    >
      <ResponsiveContainer width="100%" height={260}>
        <BarChart data={data} margin={{ top: 8, right: 12, left: 0, bottom: 0 }}>
          <CartesianGrid strokeDasharray="3 3" stroke={gridStroke} vertical={false} />
          <XAxis
            dataKey="label"
            tick={axisTick}
            axisLine={axisLine}
            tickLine={false}
            minTickGap={24}
          />
          <YAxis
            allowDecimals={false}
            tick={axisTick}
            axisLine={false}
            tickLine={false}
            width={28}
          />
          <Tooltip contentStyle={tooltipStyle} />
          <Bar dataKey="count" name="Workouts" fill={CHART_COLORS.ink} radius={[4, 4, 0, 0]} />
        </BarChart>
      </ResponsiveContainer>
      <p className="chart-footnote">Weekly counts from your logged workouts in the selected range.</p>
    </ChartCard>
  );
}
