/** Format ISO date strings for chart axes / labels. */
export function shortDate(iso: string | null | undefined): string {
  if (!iso) return "";
  const d = new Date(iso);
  if (Number.isNaN(d.getTime())) return iso.slice(0, 10);
  return d.toLocaleDateString(undefined, { month: "short", day: "numeric" });
}

export function formatNumber(value: number | null | undefined, digits = 1): string {
  if (value == null || Number.isNaN(value)) return "—";
  return value.toFixed(digits);
}

/** Amber opacity ladder: in-band full amber, farther from band more faded. */
export function recoveryColor(score: number | null | undefined): string {
  if (score == null || Number.isNaN(score)) return "#8A8A8A";
  if (score < 34) return "rgba(255,196,0,0.35)";
  if (score < 67) return "rgba(255,196,0,0.6)";
  return "#FFC400";
}

export function recoveryBand(score: number | null | undefined): string {
  if (score == null || Number.isNaN(score)) return "—";
  if (score < 34) return "Low";
  if (score < 67) return "Moderate";
  return "High";
}

export const RANGE_OPTIONS = [14, 21, 45, 90] as const;
export type RangeDays = (typeof RANGE_OPTIONS)[number];
export const DEFAULT_RANGE_DAYS: RangeDays = 21;

export function isWithinDays(iso: string | null | undefined, days: number): boolean {
  if (!iso) return false;
  const t = new Date(iso).getTime();
  if (Number.isNaN(t)) return false;
  return t >= Date.now() - days * 24 * 60 * 60 * 1000;
}

export function filterByDays<T>(
  records: T[],
  getDate: (record: T) => string | null | undefined,
  days: number,
): T[] {
  return records.filter((record) => isWithinDays(getDate(record), days));
}
