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

function matchLeadingCase(source: string, replacement: string): string {
  const si = source.search(/[A-Za-z]/);
  const ri = replacement.search(/[A-Za-z]/);
  if (si < 0 || ri < 0) return replacement;
  if (source[si] !== source[si].toUpperCase()) return replacement;
  return replacement.slice(0, ri) + replacement[ri].toUpperCase() + replacement.slice(ri + 1);
}

type TriScaleRule =
  | { re: RegExp; to: string }
  | { re: RegExp; fn: (match: string, ...groups: string[]) => string };

const TRI_SCALE_REWRITES: TriScaleRule[] = [
  {
    re: /(\d+)\s+green\s*·\s*(\d+)\s+yellow\s*·\s*(\d+)\s+red(?:\s*\((\d+)\s+days\))?/gi,
    fn: (_m, g, y, r, total) => {
      const out = Number(y) + Number(r);
      const days = total ? ` (${total} days)` : "";
      return `${g} in-band · ${out} out-of-band${days}`;
    },
  },
  { re: /in the green recovery band/gi, to: "in-band" },
  { re: /in the green recovery zone/gi, to: "in-band" },
  { re: /in the yellow recovery zone/gi, to: "out-of-band" },
  { re: /in the red recovery zone/gi, to: "out-of-band" },
  { re: /recovery in the green zone/gi, to: "in-band recovery" },
  { re: /recovery in the yellow zone/gi, to: "out-of-band recovery" },
  { re: /recovery in the red zone/gi, to: "out-of-band recovery" },
  { re: /in the green zone/gi, to: "in-band" },
  { re: /in the yellow zone/gi, to: "out-of-band" },
  { re: /in the red zone/gi, to: "out-of-band" },
  { re: /green recovery streak/gi, to: "in-band streak" },
  { re: /green recovery band/gi, to: "in-band" },
  { re: /green recovery zone/gi, to: "in-band" },
  { re: /yellow recovery zone/gi, to: "out-of-band" },
  { re: /red recovery zone/gi, to: "out-of-band" },
  { re: /historical green run/gi, to: "historical in-band run" },
  { re: /current green streak/gi, to: "current in-band streak" },
  { re: /a green streak/gi, to: "an in-band streak" },
  { re: /a yellow streak/gi, to: "an out-of-band streak" },
  { re: /a red streak/gi, to: "an out-of-band streak" },
  { re: /green streak/gi, to: "in-band streak" },
  { re: /sub-green days/gi, to: "out-of-band days" },
  { re: /yellow\/red days/gi, to: "out-of-band days" },
  { re: /yellow\/red/gi, to: "out-of-band" },
  { re: /below green/gi, to: "out-of-band" },
  { re: /few green days/gi, to: "few in-band days" },
  { re: /green days/gi, to: "in-band days" },
  { re: /sit in yellow/gi, to: "sit out-of-band" },
  { re: /(\d+(?:\.\d+)?)%\s*green\b/gi, to: "$1% in-band" },
  { re: /(\d+)\s+green\b/gi, to: "$1 in-band" },
  { re: /(\d+)\s+yellow\b/gi, to: "$1 out-of-band" },
  { re: /(\d+)\s+red\b/gi, to: "$1 out-of-band" },
  { re: /\bgreen\b/gi, to: "in-band" },
  { re: /\byellow\b/gi, to: "out-of-band" },
  { re: /\bred\b/gi, to: "out-of-band" },
];

/** Map WHOOP green/yellow/red copy to in-band / out-of-band at render time. */
export function rewriteTriScaleCopy(text: string | null | undefined): string {
  if (!text) return "";
  let out = text;
  for (const rule of TRI_SCALE_REWRITES) {
    out = out.replace(rule.re, (match, ...rest) => {
      const groups = rest.slice(0, -2) as string[];
      const replaced =
        "fn" in rule
          ? rule.fn(match, ...groups)
          : rule.to.replace(/\$(\d+)/g, (_, n) => String(groups[Number(n) - 1] ?? ""));
      return matchLeadingCase(match, replaced);
    });
  }
  return out;
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
