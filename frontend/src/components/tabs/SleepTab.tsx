import type { DerivedRead, InsightsResponse } from "../../types";
import { StageDependencyPreview } from "../deepDives/StageDependencyDive";
import { InsightsPanel } from "../InsightsPanel";
import { ReadsTable } from "../ReadsTable";
import { Section } from "../Section";

/**
 * How your nights actually went, as against how many hours they lasted.
 * Nothing here is a number the WHOOP app already puts on its own home
 * screen — that all lives in the From WHOOP tab.
 */
export default function SleepTab({
  reads,
  insights,
  onOpenRead,
}: {
  reads: DerivedRead[];
  insights: InsightsResponse | null;
  onOpenRead: (id: string) => void;
}) {
  const group = reads.filter((read) => read.group === "sleep");
  const stage = group.find((read) => read.id === "stage_dependency");

  return (
    <>
      {stage ? (
        <Section
          id="sleep-shape"
          title="The shape of your nights"
          ask="What is driving the shape of my sleep, and which stage should I be protecting?"
        >
          <StageDependencyPreview read={stage} onOpen={() => onOpenRead("stage_dependency")} />
        </Section>
      ) : null}

      {insights ? (
        <InsightsPanel
          insights={insights}
          id="sleep-insights"
          title="Sleep against recovery"
          ask="How is my sleep affecting my recovery?"
          charts={[]}
          cardIds={["sleep_recovery"]}
          showBrief={false}
          showMeta={false}
          showDisclaimer={false}
        />
      ) : null}

      {group.length > 0 ? (
        <ReadsTable reads={group} onOpen={onOpenRead} heading="Your sleep reads" />
      ) : null}
    </>
  );
}
