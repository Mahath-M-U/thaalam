import type {
  CardiacSportDive,
  DerivedRead,
  HyperarousalPoint,
  PhaseCalendarCell,
  PhasePenaltyBar,
  StageVarianceSlice,
  StrainScatterPoint,
} from "../types";
import { CardiacEfficiencyDive } from "./deepDives/CardiacEfficiencyDive";
import { CircadianPhaseDive } from "./deepDives/CircadianPhaseDive";
import { HyperarousalDive } from "./deepDives/HyperarousalDive";
import { StageDependencyDive } from "./deepDives/StageDependencyDive";
import { StrainSensitivityDive } from "./deepDives/StrainSensitivityDive";
import { GenericReadDive } from "./DeepDive";

/**
 * Picks the deep dive for a read, falling back to the generic one.
 *
 * Its own module so the five charted dives -- and the recharts they each
 * pull in -- load when a dive is actually opened, rather than riding in the
 * entry bundle of a dashboard whose first screen has no chart on it.
 */
export default function ReadDive({

  read,
  dive,
  onBack,
}: {
  read: DerivedRead;
  dive: Record<string, unknown>;
  onBack: () => void;
}) {
  if (read.id === "cardiac_efficiency") {
    return (
      <CardiacEfficiencyDive
        read={read}
        dive={dive as { sports?: CardiacSportDive[]; focus?: string; meaning?: string; calibrating?: boolean }}
        onBack={onBack}
      />
    );
  }
  if (read.id === "hyperarousal") {
    return (
      <HyperarousalDive
        read={read}
        dive={dive as { scatter?: HyperarousalPoint[]; meaning?: string; calibrating?: boolean; drivers?: { name: string; count: number; pct: number | null }[] }}
        onBack={onBack}
      />
    );
  }
  if (read.id === "stage_dependency") {
    return (
      <StageDependencyDive
        read={read}
        dive={dive as { variance?: StageVarianceSlice[]; stacked_14?: { date: string; rem: number | null; deep: number | null; light: number | null }[]; meaning?: string | null; calibrating?: boolean; dominant?: string | null }}
        onBack={onBack}
      />
    );
  }
  if (read.id === "strain_sensitivity") {
    return (
      <StrainSensitivityDive
        read={read}
        dive={dive as { scatter?: StrainScatterPoint[]; slope?: number | null; intercept?: number | null; trend_12w?: { date: string; slope: number | null }[]; meaning?: string; calibrating?: boolean }}
        onBack={onBack}
      />
    );
  }
  if (read.id === "circadian_phase") {
    return (
      <CircadianPhaseDive
        read={read}
        dive={dive as { calendar?: PhaseCalendarCell[]; penalty_bars?: PhasePenaltyBar[]; meaning?: string; calibrating?: boolean }}
        onBack={onBack}
      />
    );
  }
  return (
    <GenericReadDive
      read={read}
      meaning={typeof dive.meaning === "string" ? dive.meaning : null}
      onBack={onBack}
    />
  );
}
