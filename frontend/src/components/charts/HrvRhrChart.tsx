import {
  CartesianGrid,
  Legend,
  Line,
  LineChart,
  ResponsiveContainer,
  Tooltip,
  XAxis,
  YAxis,
} from "recharts";
import type { RecoveryRecord } from "../../types";
import { shortDate } from "../../utils";
import { ChartCard } from "../ChartCard";
import { CHART_COLORS, axisLine, axisTick, gridStroke, legendStyle, tooltipStyle } from "../../chartTheme";

interface Props {
  records: RecoveryRecord[];
}

export function HrvRhrChart({ records }: Props) {
  const data = records
    .filter((r) => r.cycle_start)
    .map((r) => ({
      date: r.cycle_start!,
      label: shortDate(r.cycle_start),
      hrv: r.hrv_rmssd_milli,
      rhr: r.resting_heart_rate,
    }))
    .filter((r) => r.hrv != null || r.rhr != null);

  if (data.length === 0) {
    return (
      <ChartCard title="HRV & resting heart rate">
        <p className="empty-chart">No HRV / RHR data yet</p>
      </ChartCard>
    );
  }

  return (
    <ChartCard
      title="HRV & resting heart rate"
      description="Heart rate variability (ms) and resting heart rate (bpm)."
    >
      <ResponsiveContainer width="100%" height={280}>
        <LineChart data={data} margin={{ top: 8, right: 12, left: 0, bottom: 0 }}>
          <CartesianGrid strokeDasharray="3 3" stroke={gridStroke} vertical={false} />
          <XAxis
            dataKey="label"
            tick={axisTick}
            axisLine={axisLine}
            tickLine={false}
            minTickGap={32}
          />
          <YAxis
            yAxisId="hrv"
            tick={{ fill: CHART_COLORS.hrv, fontSize: 11 }}
            axisLine={false}
            tickLine={false}
            width={36}
          />
          <YAxis
            yAxisId="rhr"
            orientation="right"
            tick={{ fill: CHART_COLORS.rhr, fontSize: 11 }}
            axisLine={false}
            tickLine={false}
            width={36}
          />
          <Tooltip contentStyle={tooltipStyle} />
          <Legend wrapperStyle={legendStyle} />
          <Line
            yAxisId="hrv"
            type="monotone"
            dataKey="hrv"
            name="HRV (ms)"
            stroke={CHART_COLORS.hrv}
            strokeWidth={2}
            dot={false}
            connectNulls
          />
          <Line
            yAxisId="rhr"
            type="monotone"
            dataKey="rhr"
            name="RHR (bpm)"
            stroke={CHART_COLORS.rhr}
            strokeWidth={2}
            dot={false}
            connectNulls
          />
        </LineChart>
      </ResponsiveContainer>
    </ChartCard>
  );
}
