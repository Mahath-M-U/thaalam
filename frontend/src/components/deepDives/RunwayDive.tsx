import { useEffect } from "react";
import type { RunwayResponse } from "../../types";
import { AskButton } from "../chat/AskButton";
import { RunwayChart } from "../RunwayCard";

interface Props {
  runway: RunwayResponse;
  onClose: () => void;
}

export function RunwayDiveContent({
  runway,
  chartHeight = 200,
}: {
  runway: RunwayResponse;
  chartHeight?: number;
}) {
  const hasChart = !runway.calibrating && runway.history.length > 0;
  const adaptation = runway.adaptation_window;
  const cta = runway.cta ?? "Ease the next two days";

  return (
    <>
      {hasChart ? (
        <RunwayChart runway={runway} height={chartHeight} />
      ) : (
        <p className="runway-calibrating">
          {runway.subtitle || "Calibrating the runway from your own nights."}
        </p>
      )}

      {runway.what_it_means && (
        <section className="runway-panel">
          <div className="runway-kicker">What it means</div>
          <p>{runway.what_it_means}</p>
        </section>
      )}

      {runway.spend.length > 0 && (
        <section className="runway-panel">
          <div className="runway-kicker">What&apos;s spending the runway</div>
          <ul className="runway-spend">
            {runway.spend.map((item) => (
              <li key={item.label}>
                <div className="runway-spend-row">
                  <span>{item.label}</span>
                  <em>{item.note}</em>
                </div>
                <div className="runway-spend-track">
                  <div className="runway-spend-fill" style={{ width: `${item.pct}%` }} />
                </div>
              </li>
            ))}
          </ul>
        </section>
      )}

      {adaptation && (
        <section className="runway-panel">
          <div className="runway-kicker">Adaptation window index</div>
          <div className="runway-window-row">
            <strong>{adaptation.state}</strong>
            <div className="runway-cells" aria-hidden="true">
              {adaptation.cells.map((fill, i) => (
                <span
                  key={i}
                  className={fill > 0 ? "on" : "off"}
                  style={fill > 0 ? { opacity: Math.max(0.35, fill) } : undefined}
                />
              ))}
            </div>
          </div>
          <p>{adaptation.copy}</p>
        </section>
      )}

      {!runway.calibrating && cta && (
        <p className="btn runway-cta" role="note">
          {cta}
        </p>
      )}

      {runway.methodology && <p className="runway-method">{runway.methodology}</p>}
    </>
  );
}

export function RunwayDive({ runway, onClose }: Props) {
  useEffect(() => {
    const onKey = (event: KeyboardEvent) => {
      if (event.key === "Escape") onClose();
    };
    window.addEventListener("keydown", onKey);
    return () => window.removeEventListener("keydown", onKey);
  }, [onClose]);

  return (
    <div className="runway-dive-backdrop" onClick={onClose} role="presentation">
      <div
        className="runway-dive"
        role="dialog"
        aria-modal="true"
        aria-labelledby="runway-dive-title"
        onClick={(event) => event.stopPropagation()}
      >
        <header className="runway-dive-header">
          <div className="runway-dive-top">
            <button type="button" className="runway-dive-back" onClick={onClose}>
              Back
            </button>
            {/* The dock sits above this modal, so it is usable from here. */}
            <AskButton
              question="What is limiting my runway right now, and what would extend it?"
              label="Ask about my runway"
              send
            />
          </div>
          <div className="runway-kicker">Recovery sustainability runway</div>
          <h2 id="runway-dive-title">{runway.headline ?? "Calibrating"}</h2>
        </header>
        <RunwayDiveContent runway={runway} />
      </div>
    </div>
  );
}
