/**
 * The vitality ring.
 *
 * Its own module rather than part of `VitalityDeepDive` because the ring is
 * plain SVG and the dive is recharts: keeping them together meant every
 * screen that shows the ring pulled the entire charting library into the
 * entry bundle.
 */
export function ScoreRing({
  score,
  dimmed = false,
  size = 152,
}: {
  score: number | null;
  dimmed?: boolean;
  size?: number;
}) {
  const stroke = 12;
  const r = (size - stroke) / 2;
  const c = 2 * Math.PI * r;
  const pct = Math.max(0, Math.min(1, (score ?? 0) / 1000));
  const dash = pct * c;
  const cx = size / 2;

  return (
    <div className={`score-ring${dimmed ? " is-dimmed" : ""}`} style={{ width: size, height: size }}>
      <svg width={size} height={size} viewBox={`0 0 ${size} ${size}`} aria-hidden="true">
        <circle cx={cx} cy={cx} r={r} fill="none" stroke="#333333" strokeWidth={stroke} />
        <circle
          cx={cx}
          cy={cx}
          r={r}
          fill="none"
          stroke="#FFC400"
          strokeWidth={stroke}
          strokeLinecap="round"
          strokeDasharray={`${dash} ${c}`}
          transform={`rotate(-90 ${cx} ${cx})`}
        />
      </svg>
      <div className="score-ring-center">
        <strong>{score == null ? "—" : score}</strong>
        <em>of 1000</em>
        <span>Vitality</span>
      </div>
    </div>
  );
}
