import { Cell, Pie, PieChart, ResponsiveContainer, Tooltip, Area, AreaChart, CartesianGrid, XAxis, YAxis } from "recharts";
import type { DerivedRead, StageVarianceSlice } from "../../types";
import { ChartCard } from "../ChartCard";
import { CalibratingNote, DeepDive } from "../DeepDive";
import { shortDate } from "../../utils";
import { INK, INK_35, INK_60, MUTED_SOFT, axisLine, axisTick, gridStroke, tooltipStyle } from "../../chartTheme";

const STAGE_COLORS: Record<string, string> = {
  REM: INK,
  Deep: INK_60,
  Light: "#d6d3d1",
};

interface StackedNight {
  date: string;
  rem: number | null;
  deep: number | null;
  light: number | null;
}

interface Dive {
  variance?: StageVarianceSlice[];
  stacked_14?: StackedNight[];
  nights?: number;
  needed?: number;
  calibrating?: boolean;
  dominant?: string | null;
  meaning?: string | null;
}

interface Props {
  read: DerivedRead;
  dive: Dive;
  onBack: () => void;
}

export function StageDependencyDive({ read, dive, onBack }: Props) {
  const variance = (dive.variance ?? []).filter((s) => s.pct != null);
  const stacked = (dive.stacked_14 ?? []).map((p) => ({
    ...p,
    label: shortDate(p.date),
    rem: p.rem ?? 0,
    deep: p.deep ?? 0,
    light: p.light ?? 0,
  }));
  const dominant = dive.dominant ?? variance[0]?.stage ?? "REM";
  const pct = variance.find((s) => s.stage === dominant)?.pct ?? variance[0]?.pct ?? 0;

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
        dive.calibrating || variance.length === 0 ? (
          <CalibratingNote progress={read.progress} needed={read.progress_needed} label="stage dependency" />
        ) : (
          <ChartCard title="Share of the stage–HRV link" description="Absolute partial-correlation mass for each stage versus your next-morning HRV, normalised to 100%.">
            <div className="donut-wrap">
              <ResponsiveContainer width="100%" height={220}>
                <PieChart>
                  <Pie
                    data={variance}
                    dataKey="pct"
                    nameKey="stage"
                    cx="50%"
                    cy="50%"
                    innerRadius={62}
                    outerRadius={90}
                    paddingAngle={2}
                    stroke="#ffffff"
                    strokeWidth={2}
                  >
                    {variance.map((s) => (
                      <Cell key={s.stage} fill={STAGE_COLORS[s.stage] ?? MUTED_SOFT} />
                    ))}
                  </Pie>
                  <Tooltip
                    contentStyle={tooltipStyle}
                    formatter={(value) => [
                      typeof value === "number" ? `${value.toFixed(0)}%` : value,
                      "Share",
                    ]}
                  />
                </PieChart>
              </ResponsiveContainer>
              <div className="donut-center">
                <strong>{pct.toFixed(0)}%</strong>
                <span>{dominant}</span>
              </div>
            </div>
            <ul className="stage-legend">
              {variance.map((s) => (
                <li key={s.stage}>
                  <span className="swatch" style={{ background: STAGE_COLORS[s.stage] ?? MUTED_SOFT }} />
                  {s.stage}
                  <em>{(s.pct ?? 0).toFixed(0)}%</em>
                </li>
              ))}
            </ul>
          </ChartCard>
        )
      }
    >
      {stacked.length > 0 ? (
        <ChartCard
          title="Last 14 nights · stage minutes"
          description="Real stage minutes from your nights — no filler points."
        >
          <ResponsiveContainer width="100%" height={220}>
            <AreaChart data={stacked} margin={{ top: 8, right: 8, left: 0, bottom: 0 }}>
              <CartesianGrid strokeDasharray="3 3" stroke={gridStroke} vertical={false} />
              <XAxis dataKey="label" tick={axisTick} axisLine={axisLine} tickLine={false} minTickGap={16} />
              <YAxis tick={axisTick} axisLine={false} tickLine={false} width={32} />
              <Tooltip contentStyle={tooltipStyle} />
              <Area type="monotone" dataKey="deep" name="Deep" stackId="s" stroke="none" fill={INK_35} />
              <Area type="monotone" dataKey="rem" name="REM" stackId="s" stroke="none" fill={INK} />
              <Area type="monotone" dataKey="light" name="Light" stackId="s" stroke="none" fill="#d6d3d1" />
            </AreaChart>
          </ResponsiveContainer>
          <ul className="stage-legend">
            <li>
              <span className="swatch" style={{ background: INK }} />
              REM
            </li>
            <li>
              <span className="swatch" style={{ background: INK_35 }} />
              Deep
            </li>
            <li>
              <span className="swatch" style={{ background: "#d6d3d1" }} />
              Light
            </li>
          </ul>
        </ChartCard>
      ) : (
        <p className="empty-chart">Not enough scored nights yet for a 14-night stage stack.</p>
      )}
    </DeepDive>
  );
}

export function StageDependencyPreview({
  read,
  onOpen,
}: {
  read: DerivedRead;
  onOpen: () => void;
}) {
  const preview = read.preview as { variance?: StageVarianceSlice[]; dominant?: string; pct?: number } | null;
  const variance = preview?.variance ?? [];
  if (read.calibrating || variance.length === 0) {
    return (
      <ChartCard title="Sleep Stage Dependency" description="Which stage tracks your next-morning HRV">
        <CalibratingNote progress={read.progress} needed={read.progress_needed} label="stage dependency" />
        <p className="chart-footnote">{read.methodology}</p>
      </ChartCard>
    );
  }
  const dominant = preview?.dominant ?? variance[0]?.stage ?? "REM";
  const pct = preview?.pct ?? variance[0]?.pct ?? 0;
  return (
    <ChartCard title="Sleep Stage Dependency" description="Which sleep stage carries the strongest association with your next-day HRV">
      <button type="button" className="chart-open" onClick={onOpen}>
        <span className="four-up-value">{pct.toFixed(0)}%</span>
      </button>
      <div className="donut-wrap">
        <ResponsiveContainer width="100%" height={180}>
          <PieChart>
            <Pie
              data={variance}
              dataKey="pct"
              nameKey="stage"
              cx="50%"
              cy="50%"
              innerRadius={48}
              outerRadius={72}
              paddingAngle={2}
              stroke="#ffffff"
              strokeWidth={2}
            >
              {variance.map((s) => (
                <Cell key={s.stage} fill={STAGE_COLORS[s.stage] ?? MUTED_SOFT} />
              ))}
            </Pie>
          </PieChart>
        </ResponsiveContainer>
        <div className="donut-center">
          <strong>{pct.toFixed(0)}%</strong>
          <span>{dominant}</span>
        </div>
      </div>
      <p className="chart-footnote">{read.methodology}</p>
    </ChartCard>
  );
}
