import {
  Area,
  AreaChart,
  CartesianGrid,
  ResponsiveContainer,
  Tooltip,
  XAxis,
  YAxis,
} from "recharts";
import type { CycleRecord } from "../../types";
import { shortDate } from "../../utils";
import { ChartCard } from "../ChartCard";
import { AMBER_14, axisLine, axisTick, CHART_COLORS, gridStroke, tooltipStyle } from "../../chartTheme";

interface Props {
  records: CycleRecord[];
}

export function StrainChart({ records }: Props) {
  const data = records
    .filter((r) => r.strain != null && r.start)
    .map((r) => ({
      date: r.start!,
      label: shortDate(r.start),
      strain: r.strain as number,
    }));

  if (data.length === 0) {
    return (
      <ChartCard title="Day strain over time" wide>
        <p className="empty-chart">No scored strain data yet</p>
      </ChartCard>
    );
  }

  return (
    <ChartCard
      title="Day strain over time"
      description="WHOOP daily strain score per physiological cycle."
      wide
    >
      <ResponsiveContainer width="100%" height={280}>
        <AreaChart data={data} margin={{ top: 8, right: 12, left: 0, bottom: 0 }}>
          <CartesianGrid strokeDasharray="3 3" stroke={gridStroke} vertical={false} />
          <XAxis
            dataKey="label"
            tick={axisTick}
            axisLine={axisLine}
            tickLine={false}
            minTickGap={32}
          />
          <YAxis
            tick={axisTick}
            axisLine={false}
            tickLine={false}
            width={36}
          />
          <Tooltip contentStyle={tooltipStyle} />
          <Area
            type="monotone"
            dataKey="strain"
            name="Strain"
            stroke={CHART_COLORS.strain}
            strokeWidth={2}
            fill={AMBER_14}
            dot={false}
          />
        </AreaChart>
      </ResponsiveContainer>
    </ChartCard>
  );
}
