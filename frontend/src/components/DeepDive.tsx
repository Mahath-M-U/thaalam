import type { ReactNode } from "react";
import type { DerivedRead } from "../types";
import { Sparkline } from "./ReadsTable";

interface Props {
  kicker: string;
  title: string;
  subtitle?: string | null;
  meaning?: string | null;
  methodology?: string | null;
  onBack: () => void;
  hero?: ReactNode;
  children?: ReactNode;
}

export function DeepDive({
  kicker,
  title,
  subtitle,
  meaning,
  methodology,
  onBack,
  hero,
  children,
}: Props) {
  return (
    <article className="deep-dive">
      <button type="button" className="deep-dive-back" onClick={onBack}>
        ← Back
      </button>
      <div className="deep-dive-kicker">{kicker}</div>
      <h2>{title}</h2>
      {subtitle ? <p className="deep-dive-sub">{subtitle}</p> : null}
      {hero ? <div className="deep-dive-hero">{hero}</div> : null}
      {meaning ? (
        <section className="what-it-means">
          <div className="what-it-means-kicker">What it means</div>
          <p>{meaning}</p>
        </section>
      ) : null}
      {children ? <div className="deep-dive-breakdown">{children}</div> : null}
      {methodology ? <p className="chart-footnote">{methodology}</p> : null}
    </article>
  );
}

const GROUP_KICKER: Record<string, string> = {
  sleep: "Sleep",
  load: "Load",
  rhythm: "Rhythm",
};

export function GenericReadDive({
  read,
  meaning,
  onBack,
}: {
  read: DerivedRead;
  meaning?: string | null;
  onBack: () => void;
}) {
  const value =
    read.calibrating || read.value == null
      ? null
      : `${formatValue(read.value, read.unit)} ${read.unit ?? ""}`.trim();
  return (
    <DeepDive
      kicker={GROUP_KICKER[read.group] ?? "Read"}
      title={read.title}
      subtitle={read.subtitle}
      meaning={meaning || (read.finding ? read.finding[0].toUpperCase() + read.finding.slice(1) + "." : null)}
      methodology={read.methodology}
      onBack={onBack}
      hero={
        read.calibrating ? (
          <CalibratingNote progress={read.progress} needed={read.progress_needed} label={read.title.toLowerCase()} />
        ) : (
          <div className="generic-hero">
            {value ? <div className="generic-value">{value}</div> : null}
            {read.delta != null ? (
              <p className="generic-delta">
                {read.delta >= 0 ? "+" : ""}
                {read.delta.toFixed(1)} vs your own baseline
              </p>
            ) : null}
            {read.sparkline.length >= 2 ? (
              <Sparkline values={read.sparkline} favourable={read.favourable !== false} width={220} height={48} />
            ) : null}
            <p>{read.finding}</p>
          </div>
        )
      }
    />
  );
}

function formatValue(value: number, unit: string | null): string {
  if (unit === "%" || unit === "min" || unit === "nights" || unit === "days" || unit === "of 7") {
    return value.toFixed(0);
  }
  return Math.abs(value) >= 10 ? value.toFixed(0) : value.toFixed(1);
}

export function CalibratingNote({
  progress,
  needed,
  label,
}: {
  progress?: number | null;
  needed?: number | null;
  label: string;
}) {
  const have = progress ?? 0;
  const want = needed ?? 0;
  const pct = want > 0 ? Math.min(100, Math.round((have / want) * 100)) : 0;
  return (
    <div className="calibrating-note">
      <p>
        {have} of {want} nights — still calibrating {label} against your own history
      </p>
      {want > 0 ? (
        <div className="calibrating-bar" aria-hidden="true">
          <span style={{ width: `${pct}%` }} />
        </div>
      ) : null}
    </div>
  );
}
