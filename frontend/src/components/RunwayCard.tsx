import { Area, ComposedChart, Line, ReferenceLine, ResponsiveContainer, YAxis } from "recharts";
import { INK, MUTED, WASH_MINT } from "../chartTheme";
import type { RunwayResponse } from "../types";

interface ChartRow {
  date: string;
  value: number | null;
  yhat: number | null;
  lo: number | null;
  cone: number | null;
  isBreak: boolean;
}

export function buildRunwayChartData(runway: RunwayResponse): ChartRow[] {
  const byDate = new Map<string, ChartRow>();
  for (const point of runway.history) {
    byDate.set(point.date, {
      date: point.date,
      value: point.value,
      yhat: null,
      lo: null,
      cone: null,
      isBreak: false,
    });
  }
  for (const point of runway.projection) {
    const prev = byDate.get(point.date) ?? {
      date: point.date,
      value: null,
      yhat: null,
      lo: null,
      cone: null,
      isBreak: false,
    };
    prev.yhat = point.yhat;
    prev.lo = point.lo;
    prev.cone = point.hi - point.lo;
    prev.isBreak = point.date === runway.baseline_break_date;
    byDate.set(point.date, prev);
  }
  return [...byDate.values()].sort((a, b) => a.date.localeCompare(b.date));
}

function dayParts(isoDate: string): [number, number, number] | null {
  const match = /^(\d{4})-(\d{2})-(\d{2})/.exec(isoDate);
  if (!match) return null;
  return [Number(match[1]), Number(match[2]), Number(match[3])];
}

function dayDiff(from: string, to: string): number {
  const a = dayParts(from);
  const b = dayParts(to);
  if (!a || !b) return 0;
  const da = Date.UTC(a[0], a[1] - 1, a[2]);
  const db = Date.UTC(b[0], b[1] - 1, b[2]);
  return Math.round((db - da) / 86_400_000);
}

/** YYYY-MM-DD as a local calendar date — not `new Date("YYYY-MM-DD")` (UTC midnight). */
function formatDayLabel(isoDate: string): string {
  const parts = dayParts(isoDate);
  if (!parts) return isoDate;
  const [y, m, d] = parts;
  return new Date(y, m - 1, d).toLocaleDateString(undefined, {
    month: "short",
    day: "numeric",
  });
}

export function runwayAxisLabels(runway: RunwayResponse): { back: string; mid: string; forward: string } {
  const history = runway.history;
  const projection = runway.projection;
  if (!history.length) {
    return { back: "", mid: "today", forward: "" };
  }
  const first = history[0].date;
  const origin = runway.as_of ?? history[history.length - 1].date;
  const backDays = Math.max(0, dayDiff(first, origin));
  const lastProj = projection.length ? projection[projection.length - 1].date : origin;
  const fwd = Math.max(0, dayDiff(origin, lastProj));
  const mid =
    runway.computed_on && origin === runway.computed_on ? "today" : formatDayLabel(origin);
  return {
    back: `${backDays} days back`,
    mid,
    forward: fwd > 0 ? `+${fwd} days projected` : mid,
  };
}

export function RunwayChart({ runway, height = 180 }: { runway: RunwayResponse; height?: number }) {
  const data = buildRunwayChartData(runway);
  const axis = runwayAxisLabels(runway);
  const baseline = runway.baseline;
  const values: number[] = [];
  for (const row of data) {
    if (row.value != null) values.push(row.value);
    if (row.yhat != null) values.push(row.yhat);
    if (row.lo != null) values.push(row.lo);
    if (row.cone != null && row.lo != null) values.push(row.lo + row.cone);
  }
  if (baseline != null) values.push(baseline);
  const min = values.length ? Math.min(...values) : 0;
  const max = values.length ? Math.max(...values) : 1;
  const pad = Math.max(1, (max - min) * 0.12);

  return (
    <div className="runway-chart">
      <ResponsiveContainer width="100%" height={height}>
        <ComposedChart data={data} margin={{ top: 10, right: 8, left: 8, bottom: 0 }}>
          <YAxis domain={[min - pad, max + pad]} hide />
          {baseline != null && (
            <ReferenceLine y={baseline} stroke={INK} strokeDasharray="3 5" strokeWidth={1.5} />
          )}
          <Area
            type="linear"
            dataKey="lo"
            stackId="cone"
            stroke="none"
            fill="transparent"
            isAnimationActive={false}
          />
          <Area
            type="linear"
            dataKey="cone"
            stackId="cone"
            stroke="none"
            fill={WASH_MINT}
            fillOpacity={0.6}
            isAnimationActive={false}
          />
          <Line
            type="linear"
            dataKey="value"
            stroke={MUTED}
            strokeWidth={2}
            dot={false}
            activeDot={false}
            isAnimationActive={false}
          />
          <Line
            type="linear"
            dataKey="yhat"
            stroke={INK}
            strokeWidth={2}
            strokeDasharray="6 5"
            isAnimationActive={false}
            activeDot={false}
            dot={(props) => {
              const { cx, cy, payload, index } = props;
              if (cx == null || cy == null || !payload?.isBreak) return <g key={index} />;
              return (
                <circle
                  key={index}
                  cx={cx}
                  cy={cy}
                  r={5}
                  fill={INK}
                  stroke="#ffffff"
                  strokeWidth={2}
                />
              );
            }}
          />
        </ComposedChart>
      </ResponsiveContainer>
      <div className="runway-axis">
        <span>{axis.back}</span>
        <span>{axis.mid}</span>
        <span>{axis.forward}</span>
      </div>
    </div>
  );
}

function titleParts(runway: RunwayResponse): { lead: string; rest: string } {
  const subtitle = (runway.subtitle ?? "").trim();
  const headline = (runway.headline ?? "").trim();
  if (runway.calibrating) {
    return { lead: "", rest: "" };
  }
  const split = subtitle.match(/^((?:≈\s*)?\d+\s+days?)\b[,\s]*(.*)$/i);
  if (split) {
    return { lead: split[1], rest: split[2] };
  }
  return { lead: headline, rest: subtitle };
}

interface Props {
  runway: RunwayResponse | null;
  onOpen: () => void;
  compact?: boolean;
}

export function RunwayCard({ runway, onOpen, compact = false }: Props) {
  if (!runway) return null;
  const parts = titleParts(runway);
  const windowState = runway.adaptation_window?.state ?? (runway.calibrating ? "—" : null);
  const hasChart = !runway.calibrating && runway.history.length > 0;

  return (
    <article
      className={`runway-card${compact ? " is-compact" : ""}`}
      onClick={onOpen}
      onKeyDown={
        compact
          ? (event) => {
              if (event.key === "Enter" || event.key === " ") {
                event.preventDefault();
                onOpen();
              }
            }
          : undefined
      }
      role={compact ? "button" : undefined}
      tabIndex={compact ? 0 : undefined}
      aria-label={compact ? "Open recovery sustainability runway" : undefined}
    >
      <header className="runway-card-header">
        <div>
          <div className="runway-kicker">Recovery sustainability runway</div>
          {(parts.lead || parts.rest) && (
            <h2 className="runway-title">
              {parts.lead ? <strong>{parts.lead}</strong> : null}
              {parts.rest ? ` ${parts.rest}` : null}
            </h2>
          )}
        </div>
        {compact ? (
          <span className="read-chevron" aria-hidden="true">
            ›
          </span>
        ) : (
          <div className="runway-chrome">
            <div>
              <span>Window</span>
              <strong>{windowState ?? "—"}</strong>
            </div>
            <div>
              <span>Cone</span>
              <strong>{runway.cone_pct}%</strong>
            </div>
            <button
              type="button"
              className="runway-open"
              onClick={(event) => {
                event.stopPropagation();
                onOpen();
              }}
            >
              Open
            </button>
          </div>
        )}
      </header>
      {hasChart ? (
        <RunwayChart runway={runway} height={compact ? 148 : 188} />
      ) : (
        <p className="runway-calibrating">{runway.subtitle}</p>
      )}
    </article>
  );
}
