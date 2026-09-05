import { Cell, Pie, PieChart, ResponsiveContainer, Tooltip } from "recharts";
import type { SleepStage } from "../../types";
import { ChartCard } from "../ChartCard";
import { INK, INK_35, INK_60, MUTED_SOFT, tooltipStyle } from "../../chartTheme";

const COLORS: Record<string, string> = {
  Light: INK_35,
  "Deep (SWS)": INK,
  REM: INK_60,
  Awake: "#d6d3d1",
};

interface Props {
  stages: SleepStage[];
}

export function SleepStagesChart({ stages }: Props) {
  if (stages.length === 0) {
    return (
      <ChartCard title="Average sleep stages">
        <p className="empty-chart">No sleep stage data yet</p>
      </ChartCard>
    );
  }

  const total = stages.reduce((sum, s) => sum + s.hours, 0);

  return (
    <ChartCard
      title="Average sleep stage breakdown"
      description="Average nightly time in bed by stage (hours)."
    >
      <div className="donut-wrap">
        <ResponsiveContainer width="100%" height={240}>
          <PieChart>
            <Pie
              data={stages}
              dataKey="hours"
              nameKey="stage"
              cx="50%"
              cy="50%"
              innerRadius={62}
              outerRadius={90}
              paddingAngle={2}
              stroke="#ffffff"
              strokeWidth={2}
            >
              {stages.map((s) => (
                <Cell key={s.stage} fill={COLORS[s.stage] ?? MUTED_SOFT} />
              ))}
            </Pie>
            <Tooltip
              contentStyle={tooltipStyle}
              formatter={(value) => [
                typeof value === "number" ? `${value.toFixed(1)}h` : value,
                "Avg",
              ]}
            />
          </PieChart>
        </ResponsiveContainer>
        <div className="donut-center">
          <strong>{total.toFixed(1)}h</strong>
          <span>time in bed</span>
        </div>
      </div>
      <ul className="stage-legend">
        {stages.map((s) => (
          <li key={s.stage}>
            <span
              className="swatch"
              style={{ background: COLORS[s.stage] ?? MUTED_SOFT }}
            />
            {s.stage}
            <em>{s.hours.toFixed(1)}h</em>
          </li>
        ))}
      </ul>
    </ChartCard>
  );
}
