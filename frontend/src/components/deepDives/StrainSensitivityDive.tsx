import {
  CartesianGrid,
  Line,
  LineChart,
  ResponsiveContainer,
  Scatter,
  ScatterChart,
  Tooltip,
  XAxis,
  YAxis,
} from "recharts";
import type { DerivedRead, StrainScatterPoint } from "../../types";
import { ChartCard } from "../ChartCard";
import { CalibratingNote, DeepDive } from "../DeepDive";
import { shortDate } from "../../utils";
import { AMBER, axisLine, axisTick, CHART_COLORS, gridStroke, tooltipStyle } from "../../chartTheme";

interface Dive {
  scatter?: StrainScatterPoint[];
  slope?: number | null;
  intercept?: number | null;
  trend_12w?: { date: string; slope: number | null }[];
  nights?: number;
  calibrating?: boolean;
  meaning?: string;
}

interface Props {
  read: DerivedRead;
  dive: Dive;
  onBack: () => void;
}

export function StrainSensitivityDive({ read, dive, onBack }: Props) {
  const points = (dive.scatter ?? []).filter((p) => p.strain != null && p.hrv != null);
  const slope = dive.slope;
  const intercept = dive.intercept;
  const fit = fitLine(points, slope, intercept);
  const trend = (dive.trend_12w ?? []).map((p) => ({ ...p, label: shortDate(p.date) }));

  return (
    <DeepDive
      kicker="Load"
      title={read.title}
      subtitle={read.subtitle}
      meaning={dive.meaning}
      methodology={read.methodology}
      onBack={onBack}
      hero={
        points.length === 0 ? (
          <CalibratingNote progress={read.progress} needed={read.progress_needed} label="strain sensitivity" />
        ) : (
          <ChartCard
            title="Next-morning HRV vs prior-day strain"
            description={
              slope != null
                ? `Fitted personal slope ${slope.toFixed(1)} ms per strain unit on your last scored days`
                : "Each dot is one morning — slope appears once 21 days are in."
            }
          >
            <ResponsiveContainer width="100%" height={280}>
              <ScatterChart margin={{ top: 8, right: 12, left: 0, bottom: 8 }}>
                <CartesianGrid strokeDasharray="3 3" stroke={gridStroke} />
                <XAxis
                  type="number"
                  dataKey="strain"
                  name="Prior strain"
                  tick={axisTick}
                  axisLine={axisLine}
                  tickLine={false}
                />
                <YAxis
                  type="number"
                  dataKey="hrv"
                  name="HRV"
                  unit=" ms"
                  tick={axisTick}
                  axisLine={false}
                  tickLine={false}
                  width={44}
                />
                <Tooltip contentStyle={tooltipStyle} />
                <Scatter name="Mornings" data={points} fill="#8A8A8A" />
                {fit.length === 2 ? (
                  <Scatter name="Fitted slope" data={fit} fill={AMBER} line={{ stroke: AMBER, strokeWidth: 2 }} shape={() => <g />} />
                ) : null}
              </ScatterChart>
            </ResponsiveContainer>
          </ChartCard>
        )
      }
    >
      {trend.length > 0 ? (
        <ChartCard title="12-week slope trend" description="Each point is a 21-day slope ending that week, on real nights only.">
          <ResponsiveContainer width="100%" height={200}>
            <LineChart data={trend} margin={{ top: 8, right: 8, left: 0, bottom: 0 }}>
              <CartesianGrid strokeDasharray="3 3" stroke={gridStroke} vertical={false} />
              <XAxis dataKey="label" tick={axisTick} axisLine={axisLine} tickLine={false} minTickGap={16} />
              <YAxis tick={axisTick} axisLine={false} tickLine={false} width={40} />
              <Tooltip contentStyle={tooltipStyle} />
              <Line type="monotone" dataKey="slope" name="Slope" stroke={CHART_COLORS.hrv} strokeWidth={2} dot />
            </LineChart>
          </ResponsiveContainer>
        </ChartCard>
      ) : (
        <p className="empty-chart">Not enough weeks yet for a slope trend.</p>
      )}
    </DeepDive>
  );
}

export function StrainSensitivityPreview({
  read,
  onOpen,
}: {
  read: DerivedRead;
  onOpen: () => void;
}) {
  const preview = read.preview as {
    points?: StrainScatterPoint[];
    slope?: number | null;
    intercept?: number | null;
  } | null;
  const points = (preview?.points ?? []).filter((p) => p.strain != null && p.hrv != null);
  const fit = fitLine(points, preview?.slope ?? null, preview?.intercept ?? null);
  if (read.calibrating || points.length === 0) {
    return (
      <ChartCard title="Strain Sensitivity Slope" description="HRV cost per additional strain unit">
        <CalibratingNote progress={read.progress} needed={read.progress_needed} label="strain sensitivity" />
        <p className="chart-footnote">{read.methodology}</p>
      </ChartCard>
    );
  }
  return (
    <ChartCard title="Strain Sensitivity Slope" description="HRV cost per additional strain unit">
      <button type="button" className="chart-open" onClick={onOpen}>
        <span className="four-up-value">
          {preview?.slope != null ? `${preview.slope.toFixed(1)} ms / unit` : ""}
        </span>
      </button>
      <ResponsiveContainer width="100%" height={180}>
        <ScatterChart margin={{ top: 8, right: 8, left: 0, bottom: 0 }}>
          <CartesianGrid strokeDasharray="3 3" stroke={gridStroke} />
          <XAxis type="number" dataKey="strain" tick={axisTick} axisLine={axisLine} tickLine={false} />
          <YAxis type="number" dataKey="hrv" tick={axisTick} axisLine={false} tickLine={false} width={36} />
          <Tooltip contentStyle={tooltipStyle} />
          <Scatter data={points} fill="#8A8A8A" />
          {fit.length === 2 ? (
            <Scatter data={fit} fill={AMBER} line={{ stroke: AMBER, strokeWidth: 2 }} shape={() => <g />} />
          ) : null}
        </ScatterChart>
      </ResponsiveContainer>
      <p className="chart-footnote">{read.methodology}</p>
    </ChartCard>
  );
}

function fitLine(
  points: StrainScatterPoint[],
  slope: number | null | undefined,
  intercept: number | null | undefined,
): { strain: number; hrv: number }[] {
  if (slope == null || intercept == null || points.length < 2) return [];
  const xs = points.map((p) => p.strain as number);
  const lo = Math.min(...xs);
  const hi = Math.max(...xs);
  return [
    { strain: lo, hrv: intercept + slope * lo },
    { strain: hi, hrv: intercept + slope * hi },
  ];
}
