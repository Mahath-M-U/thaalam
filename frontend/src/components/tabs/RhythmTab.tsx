import type { DerivedRead, InsightsResponse } from "../../types";
import { CircadianPhasePreview } from "../deepDives/CircadianPhaseDive";
import { InsightsPanel } from "../InsightsPanel";
import { ReadsTable } from "../ReadsTable";
import { Section } from "../Section";

/**
 * Whether your days land on the same clock — phase, habit and the weekday
 * pattern underneath both.
 */
export default function RhythmTab({
  reads,
  insights,
  onOpenRead,
}: {
  reads: DerivedRead[];
  insights: InsightsResponse | null;
  onOpenRead: (id: string) => void;
}) {
  const group = reads.filter((read) => read.group === "rhythm");
  const phase = group.find((read) => read.id === "circadian_phase");

  return (
    <>
      {phase ? (
        <Section
          id="rhythm-phase"
          title="Your phase"
          ask="How far is my body clock drifting, and what is it costing me?"
        >
          <CircadianPhasePreview read={phase} onOpen={() => onOpenRead("circadian_phase")} />
        </Section>
      ) : null}

      {insights ? (
        <InsightsPanel
          insights={insights}
          id="rhythm-insights"
          title="Your week"
          ask="Which days of the week are working for me and which are not?"
          charts={["weekday_patterns"]}
          cardIds={[]}
          showBrief={false}
          showMeta={false}
          showDisclaimer={false}
        />
      ) : null}

      {group.length > 0 ? (
        <ReadsTable reads={group} onOpen={onOpenRead} heading="Your rhythm reads" />
      ) : null}
    </>
  );
}
