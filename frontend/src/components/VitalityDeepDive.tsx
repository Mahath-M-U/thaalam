import {
  CartesianGrid,
  Line,
  LineChart,
  ReferenceArea,
  ResponsiveContainer,
  Tooltip,
  XAxis,
  YAxis,
} from "recharts";
import { AMBER, axisLine, axisTick, gridStroke, tooltipStyle } from "../chartTheme";
import type { VitalityPart, VitalityResponse } from "../types";
import { shortDate } from "../utils";

export function ScoreRing({
  score,
  dimmed = false,
  size = 152,
}: {
  score: number | null;
  dimmed?: boolean;
  size?: number;
}) {
  const stroke = 12;
  const r = (size - stroke) / 2;
  const c = 2 * Math.PI * r;
  const pct = Math.max(0, Math.min(1, (score ?? 0) / 1000));
  const dash = pct * c;
  const cx = size / 2;

  return (
    <div className={`score-ring${dimmed ? " is-dimmed" : ""}`} style={{ width: size, height: size }}>
      <svg width={size} height={size} viewBox={`0 0 ${size} ${size}`} aria-hidden="true">
        <circle cx={cx} cy={cx} r={r} fill="none" stroke="#333333" strokeWidth={stroke} />
        <circle
          cx={cx}
          cy={cx}
          r={r}
          fill="none"
          stroke="#FFC400"
          strokeWidth={stroke}
          strokeLinecap="round"
          strokeDasharray={`${dash} ${c}`}
          transform={`rotate(-90 ${cx} ${cx})`}
        />
      </svg>
      <div className="score-ring-center">
        <strong>{score == null ? "—" : score}</strong>
        <em>of 1000</em>
        <span>Vitality</span>
      </div>
    </div>
  );
}

interface Props {
  vitality: VitalityResponse;
  onClose: () => void;
}

const BANDS = [
  { name: "Optimal", lo: 800, hi: 1000 },
  { name: "Balanced", lo: 600, hi: 799 },
  { name: "Building", lo: 400, hi: 599 },
  { name: "Under-moving", lo: 0, hi: 399 },
] as const;

const OPACITY = [1, 0.75, 0.55, 0.4, 0.28];

function partFill(part: VitalityPart): number {
  if (!part.max_pts) return 0;
  return Math.max(0, Math.min(100, (part.pts / part.max_pts) * 100));
}

function formatDelta(delta: number): string {
  if (delta > 0) return `+${delta}`;
  if (delta < 0) return `−${Math.abs(delta)}`;
  return "0";
}

function formatActual(part: VitalityPart): string {
  if (part.actual == null || Number.isNaN(part.actual)) return "—";
  switch (part.unit) {
    case "steps":
      return Math.round(part.actual).toLocaleString();
    case "ratio":
      return part.actual.toFixed(2);
    case "hours":
      return `${part.actual.toFixed(1)} h`;
    case "minutes":
      return `${Math.round(part.actual)} m`;
    case "strain":
      return part.actual.toFixed(1);
    default:
      return part.actual.toFixed(1);
  }
}

function formatBand(part: VitalityPart): string {
  if (part.band_lo == null || part.band_hi == null) return "—";
  if (part.unit === "steps") {
    return `${Math.round(part.band_lo).toLocaleString()}–${Math.round(part.band_hi).toLocaleString()}`;
  }
  if (part.unit === "minutes") {
    return `< ${Math.round(part.band_hi)} m`;
  }
  if (part.unit === "hours") {
    return `${part.band_lo.toFixed(1)}–${part.band_hi.toFixed(1)} h`;
  }
  if (part.unit === "ratio") {
    return `${part.band_lo.toFixed(2)}–${part.band_hi.toFixed(2)}`;
  }
  return `${part.band_lo.toFixed(1)}–${part.band_hi.toFixed(1)}`;
}

export function VitalityDeepDive({ vitality, onClose }: Props) {
  const score = vitality.score;
  const trend = vitality.trend_30d.map((p) => ({
    ...p,
    label: shortDate(p.date),
  }));
  const totalPts = vitality.parts.reduce((sum, p) => sum + p.pts, 0);

  return (
    <div className="vitality-dive-backdrop" onClick={onClose} role="presentation">
      <div
        className="vitality-dive"
        role="dialog"
        aria-modal="true"
        aria-labelledby="vitality-dive-title"
        onClick={(e) => e.stopPropagation()}
      >
        <header className="vitality-dive-head">
          <div>
            <p className="vitality-dive-kicker">Vitality score</p>
            <h2 id="vitality-dive-title">
              {score == null ? "Calibrating" : score}
              {vitality.band ? ` — ${vitality.band}` : ""}
            </h2>
            <p className="muted">{vitality.verdict}</p>
          </div>
          <button type="button" className="btn ghost" onClick={onClose}>
            Close
          </button>
        </header>

        <div className="vitality-dive-hero">
          <ScoreRing score={score} dimmed={vitality.sleep_not_closed} size={136} />
          <ol className="band-ladder">
            {BANDS.map((b) => {
              const active =
                score != null && score >= b.lo && score <= b.hi;
              return (
                <li key={b.name} className={active ? "active" : ""}>
                  <span>{b.name}</span>
                  <em>
                    {b.lo}–{b.hi}
                  </em>
                </li>
              );
            })}
          </ol>
          <div className="stacked-pts-wrap">
            <p className="score-meter-label">Points</p>
            <div className="stacked-pts" aria-label="Component points">
              {vitality.parts.map((part, i) => (
                <div
                  key={part.key}
                  className="stacked-pts-seg"
                  style={{
                    width: `${totalPts ? (part.pts / 1000) * 100 : 0}%`,
                    opacity: OPACITY[i] ?? 0.28,
                  }}
                  title={`${part.name} ${part.pts}`}
                />
              ))}
            </div>
            <ul className="stacked-pts-legend">
              {vitality.parts.map((part, i) => (
                <li key={part.key}>
                  <span
                    className="swatch"
                    style={{ background: AMBER, opacity: OPACITY[i] ?? 0.28 }}
                  />
                  {part.name}
                  <em>{part.pts}</em>
                </li>
              ))}
            </ul>
            {vitality.delta_14d != null && (
              <p className="muted">
                {formatDelta(vitality.delta_14d)} in 14 days
              </p>
            )}
          </div>
        </div>

        {vitality.sleep_not_closed && (
          <p className="score-waiting">waiting on last night</p>
        )}
        {vitality.calibrating && (
          <p className="score-waiting">Calibrating from your nights so far.</p>
        )}

        <section className="dive-section">
          <h3>Components</h3>
          <ul className="dive-parts">
            {vitality.parts.map((part) => (
              <li key={part.key}>
                <div className="dive-part-top">
                  <strong>{part.name}</strong>
                  <span>
                    {part.pts} / {part.max_pts}
                  </span>
                </div>
                <div className="score-part-track">
                  <div className="score-part-fill" style={{ width: `${partFill(part)}%` }} />
                </div>
                <p className="dive-part-meta">
                  actual {formatActual(part)} · band {formatBand(part)}
                </p>
                <p className="dive-part-note">{part.note}</p>
              </li>
            ))}
          </ul>
        </section>

        <section className="dive-section">
          <h3>30-day trend</h3>
          {trend.length === 0 ? (
            <p className="empty-chart">Not enough scored nights for a trend yet.</p>
          ) : (
            <>
              <ResponsiveContainer width="100%" height={220}>
                <LineChart data={trend} margin={{ top: 8, right: 12, left: 0, bottom: 0 }}>
                  <ReferenceArea y1={800} y2={1000} fill={AMBER} fillOpacity={0.14} />
                  <CartesianGrid strokeDasharray="3 3" stroke={gridStroke} vertical={false} />
                  <XAxis
                    dataKey="label"
                    tick={axisTick}
                    axisLine={axisLine}
                    tickLine={false}
                    minTickGap={28}
                  />
                  <YAxis
                    domain={[0, 1000]}
                    tick={axisTick}
                    axisLine={false}
                    tickLine={false}
                    width={40}
                  />
                  <Tooltip
                    contentStyle={tooltipStyle}
                    labelFormatter={(_, payload) =>
                      payload?.[0]?.payload?.date
                        ? new Date(payload[0].payload.date as string).toLocaleDateString()
                        : ""
                    }
                    formatter={(value) => [value ?? "—", "Vitality"]}
                  />
                  <Line
                    type="monotone"
                    dataKey="score"
                    stroke="#FFFFFF"
                    strokeWidth={2}
                    dot={false}
                    activeDot={{ r: 4, fill: AMBER, stroke: "#000" }}
                  />
                </LineChart>
              </ResponsiveContainer>
              <p className="chart-footnote">
                30-day vitality · white is the score · amber wash is the optimal zone 800–1000
              </p>
            </>
          )}
        </section>

        <section className="dive-section how">
          <h3>How it is calculated</h3>
          <p>
            Each component earns full credit inside its band and loses points in either
            direction — over-training costs you the same as under-moving. Component points
            are rounded, then added; the vitality score is that sum.
          </p>
          <p>
            Training load uses your 7-day mean day strain. Daily movement uses steps when a
            source is connected; otherwise those points are redistributed. Autonomic
            readiness is last-night HRV over your 90-day HRV mean. Sleep opportunity is
            time in bed. Rhythm consistency is sleep-midpoint drift.
          </p>
          <p>
            After 60 nights the bands follow your own 90-day distribution. Until then the
            score is labelled Calibrating. If last night is still open, you see yesterday’s
            score on a dimmed ring.
          </p>
        </section>
      </div>
    </div>
  );
}
