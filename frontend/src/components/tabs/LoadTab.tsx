import type { DerivedRead, InsightsResponse, RunwayResponse } from "../../types";
import { CardiacEfficiencyPreview } from "../deepDives/CardiacEfficiencyDive";
import { StrainSensitivityPreview } from "../deepDives/StrainSensitivityDive";
import { InsightsPanel } from "../InsightsPanel";
import { ReadsTable } from "../ReadsTable";
import { RunwayCard } from "../RunwayCard";
import { Section } from "../Section";

/**
 * What your training is costing you and how long you can keep paying it.
 * The runway headline score opens here, so the card it summarises is the
 * first thing on the tab.
 */
export default function LoadTab({
  reads,
  insights,
  runway,
  onOpenRead,
  onOpenRunway,
}: {
  reads: DerivedRead[];
  insights: InsightsResponse | null;
  runway: RunwayResponse | null;
  onOpenRead: (id: string) => void;
  onOpenRunway: () => void;
}) {
  const group = reads.filter((read) => read.group === "load");
  const cardiac = group.find((read) => read.id === "cardiac_efficiency");
  const sensitivity = group.find((read) => read.id === "strain_sensitivity");

  return (
    <>
      <Section
        id="load-runway"
        title="How long you can hold this"
        ask="Is my training load sustainable right now, and what is spending my runway?"
      >
        <RunwayCard runway={runway} onOpen={onOpenRunway} />
      </Section>

      {cardiac || sensitivity ? (
        <Section
          id="load-signals"
          title="How load lands on you"
          ask="Which sports cost me the most recovery, and how sensitive am I to strain?"
        >
          {cardiac ? (
            <CardiacEfficiencyPreview
              read={cardiac}
              onOpen={() => onOpenRead("cardiac_efficiency")}
            />
          ) : null}
          {sensitivity ? (
            <StrainSensitivityPreview
              read={sensitivity}
              onOpen={() => onOpenRead("strain_sensitivity")}
            />
          ) : null}
        </Section>
      ) : null}

      {insights ? (
        <InsightsPanel
          insights={insights}
          id="load-insights"
          title="Load and autonomic baselines"
          ask="Is my training load ratio in a sensible place, and what are my HRV and resting heart rate doing against my own baseline?"
          charts={["training_load", "strain_recovery_lag", "hrv"]}
          cardIds={["acwr", "strain_recovery_lag", "training_readiness", "hrv_baseline", "rhr_baseline"]}
          showBrief={false}
          showMeta={false}
        />
      ) : null}

      {group.length > 0 ? (
        <ReadsTable reads={group} onOpen={onOpenRead} heading="Your load reads" />
      ) : null}
    </>
  );
}
