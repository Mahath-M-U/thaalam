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

export function recoveryColor(score: number | null | undefined): string {
  if (score == null || Number.isNaN(score)) return "#a8a29e";
  if (score < 34) return "#dc2626";
  if (score < 67) return "#d97706";
  return "#16a34a";
}

export function recoveryBand(score: number | null | undefined): string {
  if (score == null || Number.isNaN(score)) return "—";
  if (score < 34) return "Low";
  if (score < 67) return "Moderate";
  return "High";
}
