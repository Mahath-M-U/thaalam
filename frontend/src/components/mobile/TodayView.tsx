import { useEffect, useRef, useState } from "react";
import type { DailyBriefResponse, DerivedRead, RunwayResponse, VitalityResponse } from "../../types";
import { rewriteTriScaleCopy } from "../../utils";
import { Sparkline } from "../ReadsTable";
import { RunwayCard } from "../RunwayCard";
import { ScoreMeters } from "../ScoreRingCard";
import { ScoreRing, VitalityDeepDive } from "../VitalityDeepDive";
import { WhoopConnectionPanel } from "../WhoopConnectionPanel";

const SIGNAL_IDS = [
  "restorative_yield",
  "strain_sensitivity",
  "circadian_phase",
  "cardiac_efficiency",
] as const;

interface Props {
  vitality: VitalityResponse;
  brief: DailyBriefResponse | null;
  reads: DerivedRead[];
  runway: RunwayResponse | null;
  onOpenRead: (id: string) => void;
  onOpenReads: () => void;
  onOpenRunway: () => void;
  onRefresh: () => void;
  syncing: boolean;
  syncError?: string | null;
  /** Ground truth behind syncError; see WhoopConnectionPanel. */
  whoopConnected?: boolean | null;
  isAdmin?: boolean;
  onVitalityOpenChange?: (open: boolean) => void;
}

export function TodayView({
  vitality,
  brief,
  reads,
  runway,
  onOpenRead,
  onOpenReads,
  onOpenRunway,
  onRefresh,
  syncing,
  syncError,
  whoopConnected = null,
  isAdmin = false,
  onVitalityOpenChange,
}: Props) {
  const [vitalityOpen, setVitalityOpen] = useState(false);
  const [settingsOpen, setSettingsOpen] = useState(false);
  const settingsRef = useRef<HTMLDivElement>(null);
  const signals = SIGNAL_IDS.map((id) => reads.find((row) => row.id === id)).filter(
    (row): row is DerivedRead => Boolean(row),
  );
  const flagged = reads.filter((row) => row.flagged && !row.calibrating);

  useEffect(() => {
    onVitalityOpenChange?.(vitalityOpen);
    return () => onVitalityOpenChange?.(false);
  }, [vitalityOpen, onVitalityOpenChange]);

  useEffect(() => {
    if (vitalityOpen) setSettingsOpen(false);
  }, [vitalityOpen]);

  useEffect(() => {
    if (!settingsOpen) return;
    const onPointer = (event: PointerEvent) => {
      if (!settingsRef.current?.contains(event.target as Node)) {
        setSettingsOpen(false);
      }
    };
    const onKey = (event: KeyboardEvent) => {
      if (event.key === "Escape") setSettingsOpen(false);
    };
    document.addEventListener("pointerdown", onPointer);
    window.addEventListener("keydown", onKey);
    return () => {
      document.removeEventListener("pointerdown", onPointer);
      window.removeEventListener("keydown", onKey);
    };
  }, [settingsOpen]);

  return (
    <div className="today-view">
      <header className="today-header">
        <div>
          <div className="today-kicker">{formatDateKicker(brief?.date)}</div>
          <h1 className="today-wordmark">Thaalam</h1>
        </div>
        <div className="today-settings-wrap" ref={settingsRef}>
          <button
            type="button"
            className="today-settings"
            aria-label="Settings"
            aria-haspopup="menu"
            aria-expanded={settingsOpen}
            aria-controls="today-settings-menu"
            onClick={() => setSettingsOpen((open) => !open)}
          >
            <SettingsIcon />
          </button>
          {settingsOpen ? (
            <div className="today-settings-menu" id="today-settings-menu" role="menu">
              {/* Sync is admin-only server-side; don't offer a viewer a 403
                  (matches the desktop sidebar's refresh control). */}
              {!isAdmin ? null : syncError ? (
                <div className="today-settings-error">
                  <WhoopConnectionPanel
                    connected={whoopConnected}
                    isAdmin={isAdmin}
                    syncing={syncing}
                    detail={syncError}
                    onCheckAgain={() => {
                      setSettingsOpen(false);
                      onRefresh();
                    }}
                  />
                </div>
              ) : (
                <button
                  type="button"
                  role="menuitem"
                  disabled={syncing}
                  onClick={() => {
                    setSettingsOpen(false);
                    onRefresh();
                  }}
                >
                  {syncing ? "Syncing…" : "Refresh data"}
                </button>
              )}
            </div>
          ) : null}
        </div>
      </header>

      <section className={`today-score${vitality.sleep_not_closed ? " dimmed" : ""}`}>
        <div className="today-score-top">
          <button
            type="button"
            className="today-ring-btn"
            onClick={() => setVitalityOpen(true)}
            aria-label="Open vitality score deep dive"
          >
            <ScoreRing score={vitality.score} dimmed={vitality.sleep_not_closed} size={148} />
          </button>
          <ScoreMeters supporting={vitality.supporting} />
        </div>
      </section>

      <button
        type="button"
        className="today-band"
        onClick={() => setVitalityOpen(true)}
      >
        <div>
          <strong>
            {vitality.band || (vitality.calibrating ? "Calibrating" : "Vitality")}
            {vitality.delta_14d != null ? ` · ${formatDelta(vitality.delta_14d)} in 14 days` : ""}
          </strong>
          <p>
            {vitality.sleep_not_closed
              ? "waiting on last night"
              : vitality.cause || "Calibrating from your nights so far."}
          </p>
        </div>
        <span className="read-chevron" aria-hidden="true">
          ›
        </span>
      </button>

      <article className="today-read">
        <div className="today-read-kicker">Today&apos;s read</div>
        <p>
          {brief?.ready
            ? rewriteTriScaleCopy(brief.brief)
            : rewriteTriScaleCopy(brief?.message) || "Not enough data yet for today's read."}
        </p>
      </article>

      {runway ? (
        <RunwayCard runway={runway} onOpen={onOpenRunway} compact />
      ) : (
        <article className="runway-card is-compact">
          <div className="runway-kicker">Recovery sustainability runway</div>
          <p className="runway-calibrating">Calibrating the runway from your own nights.</p>
        </article>
      )}

      {signals.length > 0 ? (
        <section className="today-signals">
          <div className="today-signals-kicker">Your signals today</div>
          <div className="today-signals-grid">
            {signals.map((read) => (
              <button
                key={read.id}
                type="button"
                className="signal-card"
                onClick={() => onOpenRead(read.id)}
              >
                <h3>{signalTitle(read)}</h3>
                <div className="signal-card-body">
                  <div>
                    <strong>
                      {formatSignalValue(read)}
                      {read.unit && !read.calibrating && read.value != null && read.unit !== "min" ? (
                        <em>{read.unit}</em>
                      ) : null}
                    </strong>
                    <p>{signalCaption(read)}</p>
                  </div>
                  {read.calibrating || read.sparkline.length < 2 ? null : (
                    <Sparkline values={read.sparkline} favourable={read.favourable !== false} width={72} height={28} />
                  )}
                </div>
              </button>
            ))}
          </div>
        </section>
      ) : (
        <p className="today-empty">Calibrating your signals from your own nights.</p>
      )}

      {flagged.length > 0 ? (
        <section className="today-flagged">
          <div className="today-signals-kicker">Flagged last night</div>
          <ul>
            {flagged.map((read) => (
              <li key={read.id}>
                <button type="button" className="flagged-row" onClick={() => onOpenRead(read.id)}>
                  <span className="flagged-mark" aria-hidden="true">
                    !
                  </span>
                  <div>
                    <h3>{read.title}</h3>
                    <p>{read.finding}</p>
                  </div>
                  <span className="read-chevron" aria-hidden="true">
                    ›
                  </span>
                </button>
              </li>
            ))}
          </ul>
        </section>
      ) : null}

      <button type="button" className="btn today-cta" onClick={onOpenReads}>
        See all eleven reads
      </button>

      {vitalityOpen ? (
        <VitalityDeepDive vitality={vitality} onClose={() => setVitalityOpen(false)} />
      ) : null}
    </div>
  );
}

function SettingsIcon() {
  return (
    <svg viewBox="0 0 24 24" aria-hidden="true">
      <circle cx="12" cy="12" r="3.1" fill="none" stroke="currentColor" strokeWidth="1.8" />
      <path
        d="M12 3.4v1.8M12 18.8v1.8M4.9 7.4l1.55 0.9M17.55 15.7l1.55 0.9M4.9 16.6l1.55-0.9M17.55 8.3l1.55-0.9"
        fill="none"
        stroke="currentColor"
        strokeWidth="1.8"
        strokeLinecap="round"
      />
    </svg>
  );
}

/** YYYY-MM-DD as a local calendar date — not `new Date("YYYY-MM-DD")` (UTC midnight). */
function parseLocalDate(iso: string): Date {
  const match = /^(\d{4})-(\d{2})-(\d{2})/.exec(iso);
  if (match) {
    return new Date(Number(match[1]), Number(match[2]) - 1, Number(match[3]));
  }
  const parsed = new Date(iso);
  return Number.isNaN(parsed.getTime()) ? new Date() : parsed;
}

function formatDateKicker(iso?: string | null): string {
  const date = iso ? parseLocalDate(iso) : new Date();
  return date
    .toLocaleDateString("en-GB", { weekday: "long", day: "numeric", month: "long" })
    .toUpperCase();
}

function formatDelta(delta: number): string {
  if (delta > 0) return `+${delta}`;
  if (delta < 0) return `−${Math.abs(delta)}`;
  return "0";
}

function signalTitle(read: DerivedRead): string {
  if (read.id === "cardiac_efficiency") {
    const preview = read.preview as { sport?: string } | null;
    if (preview?.sport) return `Cardiac efficiency drift · ${preview.sport}`;
  }
  return read.title;
}

function formatSignalValue(read: DerivedRead): string {
  if (read.calibrating || read.value == null) return "—";
  const value = read.value;
  if (read.unit === "min") {
    const sign = value < 0 ? "−" : "";
    const abs = Math.abs(value);
    const hours = Math.floor(abs / 60);
    const minutes = Math.round(abs % 60);
    if (hours > 0) return `${sign}${hours}h ${minutes}m`;
    return `${sign}${Math.round(abs)}m`;
  }
  if (read.unit === "min/h" || read.unit === "bpm" || read.unit === "%") {
    const rounded = Math.round(value);
    if (read.unit === "bpm" && rounded > 0) return `+${rounded}`;
    return String(rounded);
  }
  if (read.unit === "ms/u") return value.toFixed(1);
  return Math.abs(value) >= 10 ? value.toFixed(0) : value.toFixed(1);
}

function signalCaption(read: DerivedRead): string {
  if (read.calibrating) {
    return `${read.progress ?? 0} of ${read.progress_needed ?? 0} — calibrating`;
  }
  if (read.id === "restorative_yield" && read.delta != null) {
    return `${formatDelta(Math.round(read.delta))} vs your norm`;
  }
  return read.finding;
}
