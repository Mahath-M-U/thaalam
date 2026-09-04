import {
  CartesianGrid,
  ResponsiveContainer,
  Scatter,
  ScatterChart,
  Tooltip,
  XAxis,
  YAxis,
  ZAxis,
} from "recharts";
import type { DailyRecord } from "../../types";
import { ChartCard } from "../ChartCard";
import { CHART_COLORS, axisLine, axisTick, gridStroke, tooltipStyle } from "../../chartTheme";

interface Props {
  records: DailyRecord[];
}

export function StrainVsRecovery({ records }: Props) {
  const data = records
    .filter((r) => r.strain != null && r.recovery_score != null)
    .map((r) => ({
      recovery: r.recovery_score as number,
      strain: r.strain as number,
      date: r.cycle_start,
    }));

  if (data.length === 0) {
    return (
      <ChartCard title="Strain vs recovery">
        <p className="empty-chart">No overlapping strain / recovery data yet</p>
      </ChartCard>
    );
  }

  return (
    <ChartCard
      title="Strain vs recovery"
      description="Same-day strain plotted against recovery score."
    >
      <ResponsiveContainer width="100%" height={280}>
        <ScatterChart margin={{ top: 8, right: 12, left: 0, bottom: 0 }}>
          <CartesianGrid strokeDasharray="3 3" stroke={gridStroke} />
          <XAxis
            type="number"
            dataKey="recovery"
            name="Recovery"
            domain={[0, 100]}
            tick={axisTick}
            axisLine={axisLine}
            tickLine={false}
          />
          <YAxis
            type="number"
            dataKey="strain"
            name="Strain"
            tick={axisTick}
            axisLine={false}
            tickLine={false}
            width={36}
          />
          <ZAxis range={[40, 40]} />
          <Tooltip
            cursor={{ strokeDasharray: "3 3" }}
            contentStyle={tooltipStyle}
            formatter={(value, name) => [value, name]}
            labelFormatter={() => ""}
          />
          <Scatter data={data} fill={CHART_COLORS.neutral} fillOpacity={0.85} />
        </ScatterChart>
      </ResponsiveContainer>
    </ChartCard>
  );
}
