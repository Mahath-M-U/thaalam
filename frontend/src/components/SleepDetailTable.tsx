import { useMemo, useState } from "react";
import type { SleepRecord } from "../types";
import { formatNumber, shortDate } from "../utils";
import { ChartCard } from "./ChartCard";

interface Props {
  records: SleepRecord[];
}

function hoursLabel(h: number | null | undefined): string {
  if (h == null || Number.isNaN(h)) return "—";
  const hrs = Math.floor(h);
  const mins = Math.round((h - hrs) * 60);
  if (hrs <= 0) return `${mins}m`;
  return mins > 0 ? `${hrs}h ${mins}m` : `${hrs}h`;
}

export function SleepDetailTable({ records }: Props) {
  const [showNaps, setShowNaps] = useState(false);
  const [limit, setLimit] = useState(21);

  const rows = useMemo(() => {
    return [...records]
      .filter((r) => (showNaps ? true : !r.nap))
      .filter((r) => r.start)
      .sort((a, b) => String(b.start).localeCompare(String(a.start)))
      .slice(0, limit);
  }, [records, showNaps, limit]);

  const latest = rows[0];

  if (records.length === 0) {
    return (
      <ChartCard title="Detailed sleep log" wide>
        <p className="empty-chart">No sleep records yet</p>
      </ChartCard>
    );
  }

  return (
    <ChartCard
      title="Detailed sleep log"
      description="Per-night duration, stages, need/debt, efficiency, consistency, and respiratory rate."
      wide
    >
      {latest?.detail && (
        <div className="sleep-latest">
          <div className="sleep-latest-title">
            Latest night · {shortDate(latest.start)}
            {latest.nap ? " (nap)" : ""}
          </div>
          <div className="sleep-latest-grid">
            <div>
              <span>Asleep</span>
              <strong>{hoursLabel(latest.detail.asleep_hours)}</strong>
            </div>
            <div>
              <span>In bed</span>
              <strong>{hoursLabel(latest.detail.in_bed_hours)}</strong>
            </div>
            <div>
              <span>Deep</span>
              <strong>{hoursLabel(latest.detail.deep_hours)}</strong>
            </div>
            <div>
              <span>REM</span>
              <strong>{hoursLabel(latest.detail.rem_hours)}</strong>
            </div>
            <div>
              <span>Light</span>
              <strong>{hoursLabel(latest.detail.light_hours)}</strong>
            </div>
            <div>
              <span>Awake</span>
              <strong>
                {latest.detail.awake_minutes != null
                  ? `${formatNumber(latest.detail.awake_minutes, 0)}m`
                  : hoursLabel(latest.detail.awake_hours)}
              </strong>
            </div>
            <div>
              <span>Need</span>
              <strong>{hoursLabel(latest.detail.need_hours)}</strong>
            </div>
            <div>
              <span>Debt</span>
              <strong>{hoursLabel(latest.detail.debt_hours)}</strong>
            </div>
            <div>
              <span>Performance</span>
              <strong>
                {latest.sleep_performance_percentage != null
                  ? `${formatNumber(latest.sleep_performance_percentage, 0)}%`
                  : "—"}
              </strong>
            </div>
            <div>
              <span>Efficiency</span>
              <strong>
                {latest.sleep_efficiency_percentage != null
                  ? `${formatNumber(latest.sleep_efficiency_percentage, 0)}%`
                  : "—"}
              </strong>
            </div>
            <div>
              <span>Disturbances</span>
              <strong>{latest.detail.disturbances ?? "—"}</strong>
            </div>
            <div>
              <span>Resp. rate</span>
              <strong>
                {latest.respiratory_rate != null
                  ? `${formatNumber(latest.respiratory_rate, 1)}`
                  : "—"}
              </strong>
            </div>
          </div>
        </div>
      )}

      <div className="table-toolbar">
        <label className="check-label">
          <input
            type="checkbox"
            checked={showNaps}
            onChange={(e) => setShowNaps(e.target.checked)}
          />
          Show naps
        </label>
        <div className="limit-btns">
          {[14, 21, 45, 90].map((n) => (
            <button
              key={n}
              type="button"
              className={limit === n ? "active" : ""}
              onClick={() => setLimit(n)}
            >
              {n}d
            </button>
          ))}
        </div>
      </div>

      <div className="table-scroll">
        <table className="data-table sleep-table">
          <thead>
            <tr>
              <th>Date</th>
              <th>Type</th>
              <th>In bed</th>
              <th>Asleep</th>
              <th>Light</th>
              <th>Deep</th>
              <th>REM</th>
              <th>Awake</th>
              <th>Perf</th>
              <th>Eff</th>
              <th>Consist</th>
              <th>Need</th>
              <th>Debt</th>
              <th>Gap</th>
              <th>Dist.</th>
              <th>Cycles</th>
              <th>RR</th>
            </tr>
          </thead>
          <tbody>
            {rows.map((r) => {
              const d = r.detail;
              return (
                <tr key={r.id}>
                  <td className="nowrap">
                    {r.start
                      ? new Date(r.start).toLocaleDateString(undefined, {
                          weekday: "short",
                          month: "short",
                          day: "numeric",
                        })
                      : "—"}
                  </td>
                  <td>
                    <span className={`badge ${r.nap ? "nap" : "main"}`}>
                      {r.nap ? "Nap" : "Main"}
                    </span>
                  </td>
                  <td>{hoursLabel(d?.in_bed_hours ?? d?.duration_hours)}</td>
                  <td>{hoursLabel(d?.asleep_hours)}</td>
                  <td>{hoursLabel(d?.light_hours)}</td>
                  <td>{hoursLabel(d?.deep_hours)}</td>
                  <td>{hoursLabel(d?.rem_hours)}</td>
                  <td>
                    {d?.awake_minutes != null
                      ? `${formatNumber(d.awake_minutes, 0)}m`
                      : hoursLabel(d?.awake_hours)}
                  </td>
                  <td>{fmtPct(r.sleep_performance_percentage)}</td>
                  <td>{fmtPct(r.sleep_efficiency_percentage)}</td>
                  <td>{fmtPct(r.sleep_consistency_percentage)}</td>
                  <td>{hoursLabel(d?.need_hours)}</td>
                  <td className={debtClass(d?.debt_hours)}>{hoursLabel(d?.debt_hours)}</td>
                  <td className={gapClass(d?.need_gap_hours)}>
                    {d?.need_gap_hours != null
                      ? `${d.need_gap_hours >= 0 ? "+" : ""}${formatNumber(d.need_gap_hours, 1)}h`
                      : "—"}
                  </td>
                  <td>{d?.disturbances ?? "—"}</td>
                  <td>{d?.sleep_cycles ?? "—"}</td>
                  <td>
                    {r.respiratory_rate != null
                      ? formatNumber(r.respiratory_rate, 1)
                      : "—"}
                  </td>
                </tr>
              );
            })}
          </tbody>
        </table>
      </div>
    </ChartCard>
  );
}

function fmtPct(v: number | null | undefined): string {
  return v == null || Number.isNaN(v) ? "—" : `${Math.round(v)}%`;
}

function debtClass(h: number | null | undefined): string {
  if (h == null) return "";
  if (h >= 1) return "warn";
  if (h >= 0.5) return "mild";
  return "ok";
}

function gapClass(h: number | null | undefined): string {
  if (h == null) return "";
  if (h < -0.5) return "warn";
  if (h < 0) return "mild";
  return "ok";
}
