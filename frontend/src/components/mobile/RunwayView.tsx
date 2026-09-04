import type { RunwayResponse } from "../../types";
import { RunwayDiveContent } from "../deepDives/RunwayDive";

interface Props {
  runway: RunwayResponse | null;
}

export function RunwayView({ runway }: Props) {
  if (!runway) {
    return (
      <div className="state-panel">
        <p>Calibrating the runway from your own nights.</p>
      </div>
    );
  }

  return (
    <div className="mobile-runway">
      <header className="runway-dive-header">
        <div className="runway-kicker">Recovery sustainability runway</div>
        <h2>{runway.headline ?? (runway.calibrating ? "Calibrating" : "Runway")}</h2>
        {runway.subtitle ? <p className="deep-dive-sub">{runway.subtitle}</p> : null}
      </header>
      <RunwayDiveContent runway={runway} />
    </div>
  );
}
