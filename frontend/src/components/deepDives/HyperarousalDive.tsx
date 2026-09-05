import {
  Bar,
  BarChart,
  CartesianGrid,
  Cell,
  ReferenceArea,
  ResponsiveContainer,
  Scatter,
  ScatterChart,
  Tooltip,
  XAxis,
  YAxis,
} from "recharts";
import type { DerivedRead, HyperarousalPoint } from "../../types";
import { ChartCard } from "../ChartCard";
import { CalibratingNote, DeepDive } from "../DeepDive";
import { INK, MUTED_SOFT, axisLine, axisTick, CHART_COLORS, gridStroke, tooltipStyle } from "../../chartTheme";

interface Dive {
  scatter?: HyperarousalPoint[];
  debt_threshold?: number | null;
  latency_threshold?: number | null;
  flagged_count?: number;
  nights?: number;
  drivers?: { name: string; count: number; pct: number | null }[];
  meaning?: string;
  calibrating?: boolean;
}

interface Props {
  read: DerivedRead;
  dive: Dive;
  onBack: () => void;
}

export function HyperarousalDive({ read, dive, onBack }: Props) {
  const points = (dive.scatter ?? []).filter(
    (p) => p.debt_hours != null && p.latency_min != null,
  );
  const flagged = points.filter((p) => p.flagged);
  const rest = points.filter((p) => !p.flagged);
  const xCut = dive.debt_threshold ?? 0;
  const yCut = dive.latency_threshold ?? 0;
  const xMax = Math.max(xCut * 1.2, ...points.map((p) => p.debt_hours ?? 0), 1);
  const yMax = Math.max(yCut * 1.2, ...points.map((p) => p.latency_min ?? 0), 1);

  return (
    <DeepDive
      kicker="Sleep"
      title={read.title}
      subtitle={read.subtitle}
      meaning={dive.meaning}
      finding={read.finding}
      methodology={read.methodology}
      onBack={onBack}
      hero={
        read.calibrating || points.length === 0 ? (
          <CalibratingNote progress={read.progress} needed={read.progress_needed} label="hyperarousal" />
        ) : (
          <ChartCard
            title="Debt × latency"
            description="Pale nights are your own history. Ink sits in the can't-get-to-sleep quadrant — high debt and long awake time versus your upper quartile."
          >
            <ResponsiveContainer width="100%" height={280}>
              <ScatterChart margin={{ top: 8, right: 12, left: 0, bottom: 8 }}>
                <CartesianGrid strokeDasharray="3 3" stroke={gridStroke} />
                <XAxis
                  type="number"
                  dataKey="debt_hours"
                  name="Debt"
                  unit=" h"
                  tick={axisTick}
                  axisLine={axisLine}
                  tickLine={false}
                  domain={[0, Math.ceil(xMax * 10) / 10]}
                />
                <YAxis
                  type="number"
                  dataKey="latency_min"
                  name="Awake"
                  unit=" min"
                  tick={axisTick}
                  axisLine={false}
                  tickLine={false}
                  width={44}
                  domain={[0, Math.ceil(yMax)]}
                />
                <Tooltip contentStyle={tooltipStyle} />
                <ReferenceArea
                  x1={xCut}
                  x2={xMax * 1.05}
                  y1={yCut}
                  y2={yMax * 1.05}
                  fill={INK}
                  fillOpacity={0.08}
                />
                <Scatter name="Other nights" data={rest} fill={MUTED_SOFT} />
                <Scatter name="Can't-get-to-sleep" data={flagged} fill={INK} />
              </ScatterChart>
            </ResponsiveContainer>
          </ChartCard>
        )
      }
    >
      {(dive.drivers ?? []).length > 0 ? (
        <ChartCard title="Drivers" description="Share of your own nights in each slice.">
          <ResponsiveContainer width="100%" height={180}>
            <BarChart data={dive.drivers} layout="vertical" margin={{ top: 4, right: 16, left: 8, bottom: 4 }}>
              <CartesianGrid strokeDasharray="3 3" stroke={gridStroke} horizontal={false} />
              <XAxis type="number" tick={axisTick} axisLine={axisLine} tickLine={false} unit="%" />
              <YAxis
                type="category"
                dataKey="name"
                width={140}
                tick={axisTick}
                axisLine={false}
                tickLine={false}
              />
              <Tooltip contentStyle={tooltipStyle} />
              <Bar dataKey="pct" name="% of nights" radius={[0, 4, 4, 0]}>
                {(dive.drivers ?? []).map((d) => (
                  <Cell key={d.name} fill={d.name.startsWith("Both") ? INK : CHART_COLORS.recoveryMid} />
                ))}
              </Bar>
            </BarChart>
          </ResponsiveContainer>
        </ChartCard>
      ) : null}
    </DeepDive>
  );
}
