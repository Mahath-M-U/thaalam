import { useState } from "react";
import {
  CartesianGrid,
  Line,
  LineChart,
  ResponsiveContainer,
  Tooltip,
  XAxis,
  YAxis,
} from "recharts";
import type { CardiacSportDive, DerivedRead } from "../../types";
import { ChartCard } from "../ChartCard";
import { CalibratingNote, DeepDive } from "../DeepDive";
import { shortDate } from "../../utils";
import {
  AMBER,
  AMBER_08,
  axisLine,
  axisTick,
  CHART_COLORS,
  gridStroke,
  tooltipStyle,
} from "../../chartTheme";

interface Dive {
  sports?: CardiacSportDive[];
  focus?: string;
  meaning?: string;
  calibrating?: boolean;
}

interface Props {
  read: DerivedRead;
  dive: Dive;
  onBack: () => void;
}

export function CardiacEfficiencyDive({ read, dive, onBack }: Props) {
  const sports = dive.sports ?? [];
  const firstEnabled = sports.find((s) => s.enabled)?.sport_name ?? sports[0]?.sport_name ?? "";
  const [sport, setSport] = useState(dive.focus || firstEnabled);
  const active = sports.find((s) => s.sport_name === sport);

  return (
    <DeepDive
      kicker="Load"
      title={read.title}
      subtitle={read.subtitle}
      meaning={dive.meaning}
      methodology={read.methodology}
      onBack={onBack}
      hero={
        sports.length === 0 ? (
          <CalibratingNote
            progress={read.progress}
            needed={read.progress_needed}
            label="cardiac efficiency"
          />
        ) : (
          <div className="sport-tabs">
            {sports.map((item) => (
              <button
                key={item.sport_name}
                type="button"
                className={`chip${sport === item.sport_name ? " active" : ""}`}
                disabled={!item.enabled}
                onClick={() => item.enabled && setSport(item.sport_name)}
              >
                {item.sport_name}
                {item.delta_bpm != null && item.enabled ? ` ${fmtDelta(item.delta_bpm)} bpm` : ""}
              </button>
            ))}
          </div>
        )
      }
    >
      {active && !active.enabled ? (
        <ChartCard title={active.sport_name}>
          <p className="empty-chart">
            Not enough matched-load sessions for {active.sport_name} yet — this tab stays off rather
            than drawing an empty chart.
          </p>
        </ChartCard>
      ) : null}
      {active?.enabled ? <SportEfficiencyChart sport={active} /> : null}
      <div className="small-multiples">
        {sports
          .filter((item) => item.enabled)
          .map((item) => (
            <SportEfficiencyChart key={item.sport_name} sport={item} compact />
          ))}
      </div>
    </DeepDive>
  );
}

export function CardiacEfficiencyPreview({
  read,
  onOpen,
}: {
  read: DerivedRead;
  onOpen: () => void;
}) {
  const preview = read.preview as
    | { series?: { date: string; hr: number | null }[]; sport?: string; delta_bpm?: number }
    | null
    | undefined;
  const series = (preview?.series ?? []).map((p) => ({
    ...p,
    label: shortDate(p.date),
  }));
  if (read.calibrating || series.length < 2) {
    return (
      <ChartCard title="Cardiac Efficiency Drift by Sport" description="Heart rate at comparable external work">
        <CalibratingNote progress={read.progress} needed={read.progress_needed} label="cardiac efficiency" />
        <p className="chart-footnote">{read.methodology}</p>
      </ChartCard>
    );
  }
  return (
    <ChartCard
      title="Cardiac Efficiency Drift by Sport"
      description={`Heart rate at comparable external work${preview?.sport ? ` · ${preview.sport}` : ""}`}
    >
      <button type="button" className="chart-open" onClick={onOpen}>
        <span className="four-up-value">
          {preview?.delta_bpm != null ? `${fmtDelta(preview.delta_bpm)} bpm` : ""}
        </span>
      </button>
      <ResponsiveContainer width="100%" height={180}>
        <LineChart data={series} margin={{ top: 8, right: 8, left: 0, bottom: 0 }}>
          <CartesianGrid strokeDasharray="3 3" stroke={gridStroke} vertical={false} />
          <XAxis dataKey="label" tick={axisTick} axisLine={axisLine} tickLine={false} minTickGap={24} />
          <YAxis tick={axisTick} axisLine={false} tickLine={false} width={36} domain={["auto", "auto"]} />
          <Tooltip contentStyle={tooltipStyle} />
          <Line type="monotone" dataKey="hr" name="Avg HR" stroke={AMBER} strokeWidth={2} dot={false} />
        </LineChart>
      </ResponsiveContainer>
      <p className="chart-footnote">{read.methodology}</p>
    </ChartCard>
  );
}

function SportEfficiencyChart({ sport, compact }: { sport: CardiacSportDive; compact?: boolean }) {
  const data = sport.series.map((p) => ({ ...p, label: shortDate(p.date) }));
  if (data.length < 2) {
    return (
      <ChartCard title={sport.sport_name}>
        <p className="empty-chart">Not enough matched-load sessions for {sport.sport_name} yet.</p>
      </ChartCard>
    );
  }
  return (
    <ChartCard
      title={sport.sport_name}
      description={
        sport.delta_bpm != null
          ? `${fmtDelta(sport.delta_bpm)} bpm versus your earlier matched sessions · ${sport.matched} sessions inside ±8% of ${sport.median_kj?.toFixed(0)} kJ`
          : `${sport.matched} matched sessions`
      }
    >
      <ResponsiveContainer width="100%" height={compact ? 140 : 220}>
        <LineChart data={data} margin={{ top: 8, right: 8, left: 0, bottom: 0 }}>
          <CartesianGrid strokeDasharray="3 3" stroke={gridStroke} vertical={false} />
          <XAxis dataKey="label" tick={axisTick} axisLine={axisLine} tickLine={false} minTickGap={24} />
          <YAxis tick={axisTick} axisLine={false} tickLine={false} width={36} domain={["auto", "auto"]} />
          <Tooltip contentStyle={tooltipStyle} />
          <Line
            type="monotone"
            dataKey="hr"
            name="Avg HR"
            stroke={CHART_COLORS.amber}
            strokeWidth={2}
            dot={false}
            fill={AMBER_08}
          />
        </LineChart>
      </ResponsiveContainer>
    </ChartCard>
  );
}

function fmtDelta(n: number): string {
  const rounded = Math.round(n);
  return rounded > 0 ? `+${rounded}` : `${rounded}`;
}
