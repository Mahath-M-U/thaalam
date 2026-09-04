import { Bar, BarChart, CartesianGrid, Cell, ResponsiveContainer, Tooltip, XAxis, YAxis } from "recharts";
import type { DerivedRead, PhaseCalendarCell, PhasePenaltyBar } from "../../types";
import { ChartCard } from "../ChartCard";
import { CalibratingNote, DeepDive } from "../DeepDive";
import { AMBER, axisLine, axisTick, gridStroke, tooltipStyle } from "../../chartTheme";

const WEEKDAYS = ["Mon", "Tue", "Wed", "Thu", "Fri", "Sat", "Sun"];

interface Dive {
  calendar?: PhaseCalendarCell[];
  penalty_bars?: PhasePenaltyBar[];
  latest_shift_min?: number | null;
  latest_penalty_ms?: number | null;
  midpoint_mean_21d?: number | null;
  nights?: number;
  calibrating?: boolean;
  meaning?: string;
}

interface Props {
  read: DerivedRead;
  dive: Dive;
  onBack: () => void;
}

export function CircadianPhaseDive({ read, dive, onBack }: Props) {
  const cells = dive.calendar ?? [];
  const bars = dive.penalty_bars ?? [];

  return (
    <DeepDive
      kicker="Rhythm"
      title={read.title}
      subtitle={read.subtitle}
      meaning={dive.meaning}
      methodology={read.methodology}
      onBack={onBack}
      hero={
        cells.length === 0 ? (
          <CalibratingNote progress={read.progress} needed={read.progress_needed} label="phase drift" />
        ) : (
          <ChartCard
            title="5 × 7 midpoint shift"
            description="Amber deepens as last night's midpoint sits farther from your own 21-night mean."
          >
            <HeatCalendar cells={cells} />
          </ChartCard>
        )
      }
    >
      {bars.some((b) => b.n > 0) ? (
        <ChartCard
          title="HRV penalty by shift size"
          description="Morning HRV versus your own mean, binned by midpoint shift on your nights."
        >
          <ResponsiveContainer width="100%" height={220}>
            <BarChart data={bars} margin={{ top: 8, right: 8, left: 0, bottom: 8 }}>
              <CartesianGrid strokeDasharray="3 3" stroke={gridStroke} vertical={false} />
              <XAxis dataKey="bucket" tick={axisTick} axisLine={axisLine} tickLine={false} interval={0} angle={-20} height={48} />
              <YAxis tick={axisTick} axisLine={false} tickLine={false} width={40} unit=" ms" />
              <Tooltip contentStyle={tooltipStyle} />
              <Bar dataKey="penalty_ms" name="HRV vs mean" radius={[4, 4, 0, 0]}>
                {bars.map((b) => (
                  <Cell key={b.bucket} fill={(b.penalty_ms ?? 0) >= 0 ? AMBER : "rgba(255,196,0,0.35)"} />
                ))}
              </Bar>
            </BarChart>
          </ResponsiveContainer>
        </ChartCard>
      ) : (
        <p className="empty-chart">Not enough shifted nights yet to bin a penalty.</p>
      )}
    </DeepDive>
  );
}

export function CircadianPhasePreview({
  read,
  onOpen,
}: {
  read: DerivedRead;
  onOpen: () => void;
}) {
  const preview = read.preview as {
    calendar?: PhaseCalendarCell[];
    penalty_bars?: PhasePenaltyBar[];
    shift_min?: number;
  } | null;
  const cells = preview?.calendar ?? [];
  const bars = preview?.penalty_bars ?? [];
  if (read.calibrating || cells.length === 0) {
    return (
      <ChartCard title="Circadian Phase Drift + penalties" description="Midpoint vs your 21-night mean">
        <CalibratingNote progress={read.progress} needed={read.progress_needed} label="phase drift" />
        <p className="chart-footnote">{read.methodology}</p>
      </ChartCard>
    );
  }
  return (
    <ChartCard title="Circadian Phase Drift + penalties" description="Sleep midpoint vs your rolling 21-night mean">
      <button type="button" className="chart-open" onClick={onOpen}>
        <span className="four-up-value">
          {preview?.shift_min != null ? `${preview.shift_min >= 0 ? "+" : ""}${preview.shift_min.toFixed(0)} min` : ""}
        </span>
      </button>
      <HeatCalendar cells={cells} />
      {bars.some((b) => b.n > 0) ? (
        <ResponsiveContainer width="100%" height={120}>
          <BarChart data={bars} margin={{ top: 8, right: 4, left: 0, bottom: 0 }}>
            <XAxis dataKey="bucket" hide />
            <YAxis hide />
            <Tooltip contentStyle={tooltipStyle} />
            <Bar dataKey="penalty_ms" radius={[3, 3, 0, 0]}>
              {bars.map((b) => (
                <Cell key={b.bucket} fill={(b.penalty_ms ?? 0) >= 0 ? AMBER : "rgba(255,196,0,0.35)"} />
              ))}
            </Bar>
          </BarChart>
        </ResponsiveContainer>
      ) : null}
      <p className="chart-footnote">{read.methodology}</p>
    </ChartCard>
  );
}

function ymd(d: Date): string {
  const y = d.getFullYear();
  const m = String(d.getMonth() + 1).padStart(2, "0");
  const day = String(d.getDate()).padStart(2, "0");
  return `${y}-${m}-${day}`;
}

function HeatCalendar({ cells }: { cells: PhaseCalendarCell[] }) {
  const absMax = Math.max(30, ...cells.map((c) => Math.abs(c.shift_min ?? 0)));
  const byDate = new Map(cells.map((c) => [c.date, c]));
  const dates = cells.map((c) => c.date).filter(Boolean).sort();
  if (dates.length === 0) return null;
  const end = new Date(`${dates[dates.length - 1]}T00:00:00`);
  if (Number.isNaN(end.getTime())) return null;
  // 5 weeks ending on the last night, Monday-start.
  const endDay = (end.getDay() + 6) % 7;
  const lastMonday = new Date(end);
  lastMonday.setDate(end.getDate() - endDay);
  const first = new Date(lastMonday);
  first.setDate(lastMonday.getDate() - 28);
  const weeks: (PhaseCalendarCell | null)[][] = [];
  const cursor = new Date(first);
  for (let w = 0; w < 5; w += 1) {
    const row: (PhaseCalendarCell | null)[] = [];
    for (let d = 0; d < 7; d += 1) {
      const key = ymd(cursor);
      row.push(byDate.get(key) ?? null);
      cursor.setDate(cursor.getDate() + 1);
    }
    weeks.push(row);
  }
  return (
    <div className="heat-cal">
      <div className="heat-cal-head">
        {WEEKDAYS.map((d) => (
          <span key={d}>{d}</span>
        ))}
      </div>
      {weeks.map((row, wi) => (
        <div key={wi} className="heat-cal-row">
          {row.map((cell, di) => {
            const shift = cell?.shift_min;
            const opacity = shift == null ? 0.08 : Math.min(1, Math.abs(shift) / absMax);
            return (
              <span
                key={`${wi}-${di}`}
                className={`heat-cell${cell ? "" : " empty"}`}
                title={
                  cell
                    ? `${cell.date}: ${shift != null ? `${shift >= 0 ? "+" : ""}${shift.toFixed(0)} min` : "—"}`
                    : undefined
                }
                style={{ background: cell ? `rgba(255,196,0,${0.15 + opacity * 0.75})` : "#131313" }}
              />
            );
          })}
        </div>
      ))}
      <div className="heat-legend">
        <span>on mean</span>
        <span className="heat-ramp">
          <i style={{ background: "rgba(255,196,0,0.15)" }} />
          <i style={{ background: "rgba(255,196,0,0.4)" }} />
          <i style={{ background: "rgba(255,196,0,0.7)" }} />
          <i style={{ background: "#FFC400" }} />
        </span>
        <span>far from your mean</span>
      </div>
    </div>
  );
}
