import type { HeadlineResponse, HeadlineScore, TabId } from "../types";

/**
 * The three derived scores, abreast.
 *
 * WHOOP's own home screen leads with Recovery, Sleep and Strain as three
 * identical percentage rings. These three are the ones it cannot show, and
 * they are deliberately *not* three matching rings: sleep quality is 0-100,
 * the runway is 0-10 days, rhythm composition is 0-1. Three different kinds
 * of quantity get three different instruments, because a shared ring shape
 * would imply a comparability that is not there.
 *
 * Each column is the entry point to its own tab -- the score and the tab it
 * summarises are the same click.
 */

interface Props {
  headline: HeadlineResponse | null;
  onOpenTab: (tab: TabId) => void;
  /** Compact drops the state line; used where vertical room is tight. */
  compact?: boolean;
}

export function HeadlineScores({ headline, onOpenTab, compact = false }: Props) {
  const scores = headline?.scores ?? [];
  if (scores.length === 0) {
    return (
      <section className="headline is-empty">
        <p className="headline-empty">
          Your three scores land here once your own nights have been read.
        </p>
      </section>
    );
  }

  return (
    <section className={`headline${compact ? " is-compact" : ""}`} aria-label="Headline scores">
      {scores.map((score) => (
        <HeadlineColumn
          key={score.id}
          score={score}
          compact={compact}
          onOpen={() => onOpenTab(score.tab)}
        />
      ))}
    </section>
  );
}

function HeadlineColumn({
  score,
  compact,
  onOpen,
}: {
  score: HeadlineScore;
  compact: boolean;
  onOpen: () => void;
}) {
  const calibrating = score.calibrating || score.value == null;
  return (
    <button
      type="button"
      className={`headline-col${calibrating ? " is-calibrating" : ""}`}
      onClick={onOpen}
      aria-label={`${score.title}: ${figureLabel(score)}. Open the ${score.tab} tab.`}
    >
      <span className="headline-kicker">{score.title}</span>

      <span className="headline-figure">
        <strong>{formatValue(score)}</strong>
        <em>{denominator(score)}</em>
      </span>

      <Rail score={score} />

      {compact ? null : (
        <span className="headline-state">
          {calibrating ? calibratingCopy(score) : score.state}
        </span>
      )}

      {score.delta_14d != null && !calibrating ? (
        <span className={`headline-delta${score.delta_14d < 0 ? " down" : ""}`}>
          {/* Compact columns are ~100px wide; the long form wraps and leaves
              the row's baselines ragged. */}
          {compact
            ? `${formatDelta(score.delta_14d)} · 14n`
            : `${formatDelta(score.delta_14d)} in 14 nights`}
        </span>
      ) : null}
    </button>
  );
}

/** One instrument per scale, picked by the shape of the quantity. */
function Rail({ score }: { score: HeadlineScore }) {
  if (score.id === "runway") return <PipRail score={score} />;
  if (score.scale === 1) return <IndexRail score={score} />;
  return <ContinuousRail score={score} />;
}

/**
 * 0-100: a continuous track with quartile ticks — the reading is "how far
 * along a range", so the instrument is a range.
 */
function ContinuousRail({ score }: { score: HeadlineScore }) {
  const pct = fraction(score) * 100;
  return (
    <span className="rail rail-continuous" aria-hidden="true">
      <span className="rail-track">
        <span className="rail-fill" style={{ width: `${pct}%` }} />
        {[25, 50, 75].map((tick) => (
          <span key={tick} className="rail-tick" style={{ left: `${tick}%` }} />
        ))}
      </span>
    </span>
  );
}

/**
 * 0-10 days: ten discrete pips, because days are counted, not measured.
 * "Holding" — no projected baseline crossing — fills every pip and caps the
 * rail open, so the best state reads as full rather than as a missing value.
 */
function PipRail({ score }: { score: HeadlineScore }) {
  const holding = Boolean(score.holding);
  const lit = score.value == null ? 0 : Math.round(score.value);
  return (
    <span className={`rail rail-pips${holding ? " is-holding" : ""}`} aria-hidden="true">
      {Array.from({ length: 10 }, (_, i) => (
        <span key={i} className={`pip${i < lit ? " is-lit" : ""}`} />
      ))}
      {holding ? <span className="pip-cap">›</span> : null}
    </span>
  );
}

/**
 * 0-1: a centred index with a marker and a midpoint hairline — the reading
 * is a position on an index, so neither end is a "fill".
 */
function IndexRail({ score }: { score: HeadlineScore }) {
  const pct = fraction(score) * 100;
  const empty = score.value == null;
  return (
    <span className="rail rail-index" aria-hidden="true">
      <span className="rail-track">
        <span className="rail-mid" />
        {empty ? null : <span className="rail-marker" style={{ left: `${pct}%` }} />}
      </span>
    </span>
  );
}

function fraction(score: HeadlineScore): number {
  if (score.value == null || !score.scale) return 0;
  return Math.max(0, Math.min(1, score.value / score.scale));
}

function formatValue(score: HeadlineScore): string {
  if (score.value == null) return "—";
  return score.value.toFixed(score.decimals);
}

function denominator(score: HeadlineScore): string {
  if (score.id === "runway") {
    return score.holding ? "days, holding" : `of ${score.scale} days`;
  }
  return score.scale === 1 ? "index" : `of ${score.scale}`;
}

function figureLabel(score: HeadlineScore): string {
  if (score.calibrating || score.value == null) return "calibrating";
  return `${formatValue(score)} ${denominator(score)}`;
}

function calibratingCopy(score: HeadlineScore): string {
  if (score.progress != null && score.progress_needed != null) {
    return `${score.progress} of ${score.progress_needed} nights — calibrating`;
  }
  return "calibrating from your own nights";
}

function formatDelta(delta: number): string {
  if (delta > 0) return `+${delta}`;
  if (delta < 0) return `−${Math.abs(delta)}`;
  return "0";
}
