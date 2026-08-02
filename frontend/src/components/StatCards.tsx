import type { LatestMetrics, StatCard } from "../types";
import { formatNumber, recoveryBand, recoveryColor } from "../utils";

interface Props {
  stats: StatCard[];
  latest: LatestMetrics;
}

export function StatCards({ stats, latest }: Props) {
  const recovery = latest.recovery_score;

  return (
    <div className="stat-grid">
      <div className="stat-card featured">
        <div className="stat-label">Latest recovery</div>
        <div className="stat-value" style={{ color: recoveryColor(recovery) }}>
          {formatNumber(recovery, 0)}
        </div>
        <div className="stat-sub">
          {recoveryBand(recovery)}
          {latest.cycle_start
            ? ` · ${new Date(latest.cycle_start).toLocaleDateString()}`
            : ""}
        </div>
      </div>

      <div className="stat-card">
        <div className="stat-label">Latest strain</div>
        <div className="stat-value">{formatNumber(latest.strain)}</div>
        <div className="stat-sub">Day strain score</div>
      </div>

      <div className="stat-card">
        <div className="stat-label">Sleep performance</div>
        <div className="stat-value">
          {latest.sleep_performance_percentage != null
            ? `${formatNumber(latest.sleep_performance_percentage, 0)}%`
            : "—"}
        </div>
        <div className="stat-sub">Last main sleep</div>
      </div>

      <div className="stat-card">
        <div className="stat-label">HRV / RHR</div>
        <div className="stat-value compact">
          {formatNumber(latest.hrv_rmssd_milli, 0)}
          <span className="unit">ms</span>
          <span className="sep">·</span>
          {formatNumber(latest.resting_heart_rate, 0)}
          <span className="unit">bpm</span>
        </div>
        <div className="stat-sub">Latest recovery metrics</div>
      </div>

      {stats.map((s) => (
        <div key={s.label} className="stat-card">
          <div className="stat-label">{s.label}</div>
          <div className="stat-value">{s.value}</div>
        </div>
      ))}
    </div>
  );
}
