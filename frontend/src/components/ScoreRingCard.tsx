import { useState } from "react";
import type { VitalityPart, VitalityResponse, VitalitySupporting } from "../types";
import { ScoreRing, VitalityDeepDive } from "./VitalityDeepDive";

interface Props {
  vitality: VitalityResponse;
}

export function ScoreMeters({
  supporting,
}: {
  supporting: VitalitySupporting | null | undefined;
}) {
  const strain = supporting?.day_strain ?? null;
  const strainMax = supporting?.day_strain_max ?? 21;
  const yieldPct = supporting?.sleep_yield ?? null;
  const rhr = supporting?.resting_hr ?? null;

  return (
    <div className="score-meters">
      <Meter
        label="Day strain"
        display={strain == null ? "—" : `${strain.toFixed(1)} / ${strainMax}`}
        fill={strain == null ? 0 : Math.max(0, Math.min(1, strain / strainMax))}
        tone="soft"
      />
      <Meter
        label="Sleep yield"
        display={yieldPct == null ? "—" : `${Math.round(yieldPct)}%`}
        fill={yieldPct == null ? 0 : Math.max(0, Math.min(1, yieldPct / 100))}
        tone="ink"
      />
      <Meter
        label="Resting HR"
        display={rhr == null ? "—" : `${Math.round(rhr)} bpm`}
        fill={rhr == null ? 0 : Math.max(0, Math.min(1, (80 - rhr) / 40))}
        tone="soft"
      />
    </div>
  );
}

export function ScoreRingCard({ vitality }: Props) {
  const [diveOpen, setDiveOpen] = useState(false);
  const score = vitality.score;
  const dimmed = vitality.sleep_not_closed;

  return (
    <>
      <article className={`score-ring-card${dimmed ? " dimmed" : ""}`}>
        <button
          type="button"
          className="score-ring-open"
          onClick={() => setDiveOpen(true)}
          aria-label="Open vitality score deep dive"
        >
          <div className="score-ring-top">
            <ScoreRing score={score} dimmed={dimmed} />
            <ScoreMeters supporting={vitality.supporting} />
          </div>

          <div className="score-ring-meta">
            <div className="score-ring-kicker">
              Vitality score
              {vitality.band ? ` · ${vitality.band}` : ""}
              {vitality.calibrating ? " · Calibrating" : ""}
            </div>
            {vitality.delta_14d != null && (
              <div className={`score-delta${vitality.delta_14d < 0 ? " down" : ""}`}>
                {formatDelta(vitality.delta_14d)} in 14 days
              </div>
            )}
          </div>

          {vitality.parts.length > 0 ? (
            <ul className="score-parts">
              {vitality.parts.map((part) => (
                <li key={part.key}>
                  <span className="score-part-name">{part.name}</span>
                  <div className="score-part-track" aria-hidden="true">
                    <div
                      className="score-part-fill"
                      style={{ width: `${partFill(part)}%` }}
                    />
                  </div>
                  <span className="score-part-pts">{part.pts}</span>
                </li>
              ))}
            </ul>
          ) : (
            <p className="score-empty">Calibrating from your nights so far.</p>
          )}

          {vitality.sleep_not_closed && (
            <p className="score-waiting">waiting on last night</p>
          )}
          {vitality.cause ? <p className="score-cause">{vitality.cause}</p> : null}
        </button>
      </article>

      {diveOpen && (
        <VitalityDeepDive vitality={vitality} onClose={() => setDiveOpen(false)} />
      )}
    </>
  );
}

function Meter({
  label,
  display,
  fill,
  tone,
}: {
  label: string;
  display: string;
  fill: number;
  tone: "soft" | "ink";
}) {
  return (
    <div className="score-meter">
      <span className="score-meter-label">{label}</span>
      <div className="score-meter-track">
        <div
          className={`score-meter-fill ${tone}`}
          style={{ width: `${Math.round(fill * 100)}%` }}
        />
      </div>
      <span className="score-meter-value">{display}</span>
    </div>
  );
}

function partFill(part: VitalityPart): number {
  if (!part.max_pts) return 0;
  return Math.max(0, Math.min(100, (part.pts / part.max_pts) * 100));
}

function formatDelta(delta: number): string {
  if (delta > 0) return `+${delta}`;
  if (delta < 0) return `−${Math.abs(delta)}`;
  return "0";
}
