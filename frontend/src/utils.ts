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

/** Temporary 34/67 opacity ladder until personal bands exist. Not an own-band. */
export function recoveryColor(score: number | null | undefined): string {
  if (score == null || Number.isNaN(score)) return "#8A8A8A";
  if (score < 34) return "rgba(255,196,0,0.35)";
  if (score < 67) return "rgba(255,196,0,0.6)";
  return "#FFC400";
}

const TRI_SCALE_REWRITES: [RegExp, string][] = [
  [/in the green recovery zone/gi, "in-band"],
  [/in the yellow recovery zone/gi, "out-of-band"],
  [/in the red recovery zone/gi, "out-of-band"],
  [/green recovery streak/gi, "in-band streak"],
  [/green recovery band/gi, "in-band"],
  [/green recovery zone/gi, "in-band"],
  [/yellow recovery zone/gi, "out-of-band"],
  [/red recovery zone/gi, "out-of-band"],
  [/historical green run/gi, "historical in-band run"],
  [/current green streak/gi, "current in-band streak"],
  [/green streak/gi, "in-band streak"],
  [/sub-green days/gi, "out-of-band days"],
  [/yellow\/red days/gi, "out-of-band days"],
  [/yellow\/red/gi, "out-of-band"],
  [/below green/gi, "out-of-band"],
  [/few green days/gi, "few in-band days"],
  [/green days/gi, "in-band days"],
  [/sit in yellow/gi, "sit out-of-band"],
  [/in the green zone/gi, "in-band"],
  [/in the yellow zone/gi, "out-of-band"],
  [/in the red zone/gi, "out-of-band"],
  [/into a green streak/gi, "into an in-band streak"],
  [/into a yellow streak/gi, "into an out-of-band streak"],
  [/into a red streak/gi, "into an out-of-band streak"],
  [/a green streak/gi, "an in-band streak"],
  [/a yellow streak/gi, "an out-of-band streak"],
  [/a red streak/gi, "an out-of-band streak"],
  [/(\d+(?:\.\d+)?)%\s*green\b/gi, "$1% in-band"],
  [/(\d+)\s+green\b/gi, "$1 in-band"],
  [/(\d+)\s+yellow\b/gi, "$1 out-of-band"],
  [/(\d+)\s+red\b/gi, "$1 out-of-band"],
  [/\bgreen\b/gi, "in-band"],
  [/\byellow\b/gi, "out-of-band"],
  [/\bred\b/gi, "out-of-band"],
];

/** Map WHOOP green/yellow/red copy to in-band / out-of-band at render time. */
export function rewriteTriScaleCopy(text: string | null | undefined): string {
  if (!text) return "";
  return TRI_SCALE_REWRITES.reduce((s, [pattern, replacement]) => s.replace(pattern, replacement), text);
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
