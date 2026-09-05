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
import type { SleepRecord } from "../../types";
import { shortDate } from "../../utils";
import { ChartCard } from "../ChartCard";
import { CHART_COLORS, axisLine, axisTick, gridStroke, legendStyle, tooltipStyle } from "../../chartTheme";

interface Props {
  records: SleepRecord[];
}

export function SleepTrendsChart({ records }: Props) {
  const data = records
    .filter((r) => r.start && !r.nap)
    .map((r) => ({
      date: r.start!,
      label: shortDate(r.start),
      performance: r.sleep_performance_percentage,
      efficiency: r.sleep_efficiency_percentage,
      consistency: r.sleep_consistency_percentage,
    }));

  if (data.length === 0) {
    return (
      <ChartCard title="Sleep trends" wide>
        <p className="empty-chart">No sleep data yet</p>
      </ChartCard>
    );
  }

  return (
    <ChartCard
      title="Sleep performance, efficiency & consistency"
      description="Key sleep quality percentages over time (naps excluded)."
      wide
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
            domain={[0, 100]}
            tick={axisTick}
            axisLine={false}
            tickLine={false}
            width={36}
          />
          <Tooltip contentStyle={tooltipStyle} />
          <Legend wrapperStyle={legendStyle} />
          <Line
            type="monotone"
            dataKey="performance"
            name="Performance"
            stroke={CHART_COLORS.ink}
            strokeWidth={2}
            dot={false}
            connectNulls
          />
          <Line
            type="monotone"
            dataKey="efficiency"
            name="Efficiency"
            stroke={CHART_COLORS.hrv}
            strokeWidth={2}
            dot={false}
            connectNulls
          />
          <Line
            type="monotone"
            dataKey="consistency"
            name="Consistency"
            stroke={CHART_COLORS.sleep}
            strokeWidth={2}
            dot={false}
            connectNulls
          />
        </LineChart>
      </ResponsiveContainer>
    </ChartCard>
  );
}
