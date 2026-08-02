import {
  CartesianGrid,
  Line,
  LineChart,
  ResponsiveContainer,
  Tooltip,
  XAxis,
  YAxis,
  ReferenceArea,
} from "recharts";
import type { RecoveryRecord } from "../../types";
import { recoveryColor, shortDate } from "../../utils";
import { ChartCard } from "../ChartCard";
import { CHART_COLORS, axisLine, axisTick, gridStroke, tooltipStyle } from "../../chartTheme";

interface Props {
  records: RecoveryRecord[];
}

export function RecoveryChart({ records }: Props) {
  const data = records
    .filter((r) => r.recovery_score != null && r.cycle_start)
    .map((r) => ({
      date: r.cycle_start!,
      label: shortDate(r.cycle_start),
      score: r.recovery_score as number,
      color: recoveryColor(r.recovery_score),
    }));

  if (data.length === 0) {
    return (
      <ChartCard title="Recovery score over time" wide>
        <p className="empty-chart">No scored recovery data yet</p>
      </ChartCard>
    );
  }

  return (
    <ChartCard
      title="Recovery score over time"
      description="Daily recovery (0–100) with red / yellow / green bands."
      wide
    >
      <ResponsiveContainer width="100%" height={280}>
        <LineChart data={data} margin={{ top: 8, right: 12, left: 0, bottom: 0 }}>
          <ReferenceArea y1={0} y2={34} fill={CHART_COLORS.recoveryLow} fillOpacity={0.07} />
          <ReferenceArea y1={34} y2={67} fill={CHART_COLORS.recoveryMid} fillOpacity={0.07} />
          <ReferenceArea y1={67} y2={100} fill={CHART_COLORS.recoveryHigh} fillOpacity={0.07} />
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
          <Tooltip
            contentStyle={tooltipStyle}
            labelFormatter={(_, payload) =>
              payload?.[0]?.payload?.date
                ? new Date(payload[0].payload.date as string).toLocaleDateString()
                : ""
            }
            formatter={(value) => [value ?? "—", "Recovery"]}
          />
          <Line
            type="monotone"
            dataKey="score"
            stroke={CHART_COLORS.neutral}
            strokeWidth={1.5}
            dot={(props) => {
              const { cx, cy, payload, index } = props;
              if (cx == null || cy == null) return <g key={index} />;
              return (
                <circle
                  key={index}
                  cx={cx}
                  cy={cy}
                  r={3.5}
                  fill={payload.color}
                  stroke="#ffffff"
                  strokeWidth={1}
                />
              );
            }}
            activeDot={{ r: 5 }}
          />
        </LineChart>
      </ResponsiveContainer>
    </ChartCard>
  );
}
