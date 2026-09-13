import { useMemo } from "react";
import type {
  DerivedRead,
  InsightsResponse,
  SportEfficiencyDelta,
  SummaryResponse,
} from "../../types";
import type { WhoopRecords } from "../../hooks/useDashboardData";
import { filterByDays, type RangeDays } from "../../utils";
import { HrvRhrChart } from "../charts/HrvRhrChart";
import { RecoveryChart } from "../charts/RecoveryChart";
import { SleepStagesChart } from "../charts/SleepStagesChart";
import { SleepTrendsChart } from "../charts/SleepTrendsChart";
import { SleepVsRecoveryChart } from "../charts/SleepVsRecoveryChart";
import { StrainChart } from "../charts/StrainChart";
import { StrainVsRecovery } from "../charts/StrainVsRecovery";
import { StrainBySportChart, WorkoutFrequencyChart } from "../charts/WorkoutCharts";
import { InsightsPanel } from "../InsightsPanel";
import { Section } from "../Section";
import { SleepDetailTable } from "../SleepDetailTable";
import { StatCards } from "../StatCards";

/**
 * Everything the WHOOP app already shows you, in one place.
 *
 * These are not bad numbers — they are just not *this* app's numbers. Kept
 * because the history behind them is worth having in one scroll, quarantined
 * because leaving them on the front page made the derived scores look like
 * more of the same.
 */
export default function WhoopTab({
  summary,
  records,
  insights,
  reads,
  rangeDays,
  onOpenRead,
}: {
  summary: SummaryResponse;
  records: WhoopRecords | null;
  insights: InsightsResponse | null;
  reads: DerivedRead[];
  rangeDays: RangeDays;
  onOpenRead: (id: string) => void;
}) {
  const recovery = useMemo(
    () => filterByDays(records?.recovery ?? [], (r) => r.cycle_start, rangeDays),
    [records, rangeDays],
  );
  const cycles = useMemo(
    () => filterByDays(records?.cycles ?? [], (r) => r.start, rangeDays),
    [records, rangeDays],
  );
  const daily = useMemo(
    () => filterByDays(records?.daily ?? [], (r) => r.cycle_start, rangeDays),
    [records, rangeDays],
  );
  const sleep = useMemo(
    () => filterByDays(records?.sleep ?? [], (r) => r.start, rangeDays),
    [records, rangeDays],
  );
  const workouts = useMemo(
    () => filterByDays(records?.workouts ?? [], (r) => r.start, rangeDays),
    [records, rangeDays],
  );

  const cardiacPreview = reads.find((read) => read.id === "cardiac_efficiency")?.preview as
    | { sports?: SportEfficiencyDelta[] }
    | undefined;

  return (
    <>
      <p className="whoop-tab-note">
        These are WHOOP&apos;s own numbers, kept for the history behind them. Your
        derived scores and reads live on the other tabs.
      </p>

      <div id="whoop-stats">
        <StatCards stats={summary.stats} latest={summary.latest} />
      </div>

      <Section
        id="whoop-recovery"
        title="Recovery"
        ask="What have my recovery, HRV and resting heart rate been doing?"
      >
        <RecoveryChart records={recovery} />
        <HrvRhrChart records={recovery} />
      </Section>

      <Section id="whoop-strain" title="Strain" ask="How has my day strain been tracking?">
        <StrainChart records={cycles} />
        <StrainVsRecovery records={daily} />
      </Section>

      <Section id="whoop-sleep" title="Sleep" ask="How have my sleep hours and stages been trending?">
        <SleepTrendsChart records={sleep} />
        <SleepStagesChart stages={records?.sleepStages ?? []} />
        {insights ? (
          <SleepVsRecoveryChart daily={daily} insights={insights} rangeDays={rangeDays} />
        ) : null}
        <SleepDetailTable records={sleep} />
      </Section>

      <Section id="whoop-workouts" title="Workouts" ask="How often am I training, and in what?">
        <WorkoutFrequencyChart workouts={workouts} />
        <StrainBySportChart
          sports={records?.sports ?? []}
          efficiencyDeltas={cardiacPreview?.sports ?? []}
          onOpenRead={onOpenRead}
        />
      </Section>

      {insights ? (
        <InsightsPanel
          insights={insights}
          id="whoop-distributions"
          title="Distributions and debt"
          ask="What do my recovery mix, streaks and sleep debt look like?"
          charts={["recovery_zones", "sleep_debt", "rolling"]}
          cardIds={["recovery_zones", "green_streak", "sleep_debt"]}
          rangeDays={rangeDays}
          showBrief={false}
          showMeta={false}
        />
      ) : null}
    </>
  );
}
