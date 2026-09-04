import {
  Bar,
  BarChart,
  CartesianGrid,
  Legend,
  Line,
  LineChart,
  ResponsiveContainer,
  Scatter,
  ScatterChart,
  Tooltip,
  XAxis,
  YAxis,
  ZAxis,
} from "recharts";
import type { DailyRecord, InsightsResponse } from "../../types";
import { formatNumber, isWithinDays, shortDate } from "../../utils";
import { ChartCard } from "../ChartCard";
import { CHART_COLORS, axisLine, axisTick, gridStroke, legendStyle, tooltipStyle } from "../../chartTheme";

interface Props {
  daily: DailyRecord[];
  insights: InsightsResponse;
  rangeDays?: number;
}

export function SleepVsRecoveryChart({ daily, insights, rangeDays }: Props) {
  const section = insights.sections?.sleep_recovery;
  const corr = section?.correlation;
  const corrEff = section?.correlation_sleep_efficiency;
  const corrCons = section?.correlation_sleep_consistency;
  const gap = section?.recovery_gap_good_vs_poor;
  const good = section?.avg_recovery_after_good_sleep;
  const poor = section?.avg_recovery_after_poor_sleep;
  const mid = section?.avg_recovery_mid_sleep;
  const n = section?.n_pairs;

  const scatter = (
    section?.scatter?.map((p) => ({
      ...p,
      label: shortDate(p.date),
    })) ??
    daily
      .filter((d) => d.sleep_performance_percentage != null && d.recovery_score != null)
      .map((d) => ({
        date: d.cycle_start ?? "",
        label: shortDate(d.cycle_start),
        sleep_performance: d.sleep_performance_percentage as number,
        recovery_score: d.recovery_score as number,
      }))
  ).filter((p) => (rangeDays == null ? true : isWithinDays(p.date, rangeDays)));

  const dual = (
    section?.dual_series?.map((p) => ({
      ...p,
      label: shortDate(p.date),
    })) ??
    daily
      .filter((d) => d.cycle_start && (d.sleep_performance_percentage != null || d.recovery_score != null))
      .map((d) => ({
        date: d.cycle_start!,
        label: shortDate(d.cycle_start),
        sleep_performance: d.sleep_performance_percentage,
        recovery_score: d.recovery_score,
      }))
  ).filter((p) => (rangeDays == null ? true : isWithinDays(p.date, rangeDays)));

  const buckets = section?.buckets ?? [];

  if (scatter.length < 5) {
    return (
      <ChartCard title="Sleep vs recovery comparison" wide>
        <p className="empty-chart">Need more paired sleep + recovery days</p>
      </ChartCard>
    );
  }

  const strength =
    corr == null
      ? "—"
      : Math.abs(corr) >= 0.5
        ? "Strong"
        : Math.abs(corr) >= 0.3
          ? "Moderate"
          : "Weak";

  return (
    <>
      <ChartCard
        title="Sleep vs recovery comparison"
        description="All history · how sleep performance lines up with same-day recovery (Pearson r + good vs poor nights). Scatter and dual-line below follow the selected range."
        wide
      >
        <div className="compare-stats">
          <div className="compare-stat">
            <span>Correlation (sleep perf → recovery)</span>
            <strong className={corr != null && corr >= 0.3 ? "pos" : ""}>
              {corr != null ? `r = ${corr >= 0 ? "+" : ""}${corr.toFixed(2)}` : "—"}
            </strong>
            <em>All history · {strength} · n = {n ?? "—"}</em>
          </div>
          <div className="compare-stat">
            <span>Recovery after good sleep</span>
            <strong className="pos">{formatNumber(good, 0)}</strong>
            <em>Top quartile sleep nights</em>
          </div>
          <div className="compare-stat">
            <span>Recovery after poor sleep</span>
            <strong className="neg">{formatNumber(poor, 0)}</strong>
            <em>Bottom quartile sleep nights</em>
          </div>
          <div className="compare-stat">
            <span>Gap (good − poor)</span>
            <strong className={gap != null && gap > 0 ? "pos" : ""}>
              {gap != null ? `${gap >= 0 ? "+" : ""}${gap.toFixed(0)}` : "—"}
            </strong>
            <em>Extra recovery points on good sleep</em>
          </div>
          {mid != null && (
            <div className="compare-stat">
              <span>Mid sleep nights</span>
              <strong>{formatNumber(mid, 0)}</strong>
              <em>Average recovery (middle 50%)</em>
            </div>
          )}
          {corrEff != null && (
            <div className="compare-stat">
              <span>Efficiency ↔ recovery</span>
              <strong>r = {corrEff >= 0 ? "+" : ""}{corrEff.toFixed(2)}</strong>
              <em>Sleep efficiency correlation</em>
            </div>
          )}
          {corrCons != null && (
            <div className="compare-stat">
              <span>Consistency ↔ recovery</span>
              <strong>r = {corrCons >= 0 ? "+" : ""}{corrCons.toFixed(2)}</strong>
              <em>Sleep consistency correlation</em>
            </div>
          )}
        </div>
      </ChartCard>

      <ChartCard
        title="Scatter: sleep performance vs recovery"
        description="Each point is one day. Up-and-right = better sleep tends to mean better recovery."
      >
        <ResponsiveContainer width="100%" height={300}>
          <ScatterChart margin={{ top: 8, right: 12, left: 0, bottom: 8 }}>
            <CartesianGrid strokeDasharray="3 3" stroke={gridStroke} />
            <XAxis
              type="number"
              dataKey="sleep_performance"
              name="Sleep %"
              domain={[0, 100]}
              tick={axisTick}
              axisLine={axisLine}
              tickLine={false}
              label={{
                value: "Sleep performance %",
                position: "insideBottom",
                offset: -2,
                fill: axisTick.fill,
                fontSize: 11,
              }}
            />
            <YAxis
              type="number"
              dataKey="recovery_score"
              name="Recovery"
              domain={[0, 100]}
              tick={axisTick}
              axisLine={false}
              tickLine={false}
              width={36}
              label={{
                value: "Recovery",
                angle: -90,
                position: "insideLeft",
                fill: axisTick.fill,
                fontSize: 11,
              }}
            />
            <ZAxis range={[50, 50]} />
            <Tooltip
              cursor={{ strokeDasharray: "3 3" }}
              contentStyle={tooltipStyle}
              formatter={(value, name) => [value, name]}
              labelFormatter={() => ""}
            />
            <Scatter data={scatter} fill={CHART_COLORS.neutral} fillOpacity={0.85} />
          </ScatterChart>
        </ResponsiveContainer>
      </ChartCard>

      {buckets.length > 0 && (
        <ChartCard
          title="Recovery by sleep quality bucket"
          description="All history · average recovery after poor / average / good sleep performance nights."
        >
          <ResponsiveContainer width="100%" height={280}>
            <BarChart data={buckets} margin={{ top: 8, right: 12, left: 0, bottom: 0 }}>
              <CartesianGrid strokeDasharray="3 3" stroke={gridStroke} vertical={false} />
              <XAxis
                dataKey="sleep_quality"
                tick={axisTick}
                axisLine={axisLine}
                tickLine={false}
              />
              <YAxis
                domain={[0, 100]}
                tick={axisTick}
                axisLine={false}
                tickLine={false}
                width={36}
              />
              <Tooltip contentStyle={tooltipStyle} />
              <Legend wrapperStyle={legendStyle} />
              <Bar
                dataKey="avg_recovery"
                name="Avg recovery"
                fill={CHART_COLORS.recovery}
                radius={[6, 6, 0, 0]}
              />
              <Bar
                dataKey="avg_sleep_performance"
                name="Avg sleep %"
                fill={CHART_COLORS.hrv}
                radius={[6, 6, 0, 0]}
              />
            </BarChart>
          </ResponsiveContainer>
        </ChartCard>
      )}

      {dual.length > 0 && (
        <ChartCard
          title="Sleep performance & recovery over time"
          description="Side-by-side trends so you can see when sleep dips and recovery follows."
          wide
        >
          <ResponsiveContainer width="100%" height={300}>
            <LineChart data={dual} margin={{ top: 8, right: 12, left: 0, bottom: 0 }}>
              <CartesianGrid strokeDasharray="3 3" stroke={gridStroke} vertical={false} />
              <XAxis
                dataKey="label"
                tick={axisTick}
                axisLine={axisLine}
                tickLine={false}
                minTickGap={28}
              />
              <YAxis
                domain={[0, 100]}
                tick={axisTick}
                axisLine={false}
                tickLine={false}
                width={36}
              />
              <Tooltip contentStyle={tooltipStyle} />
              <Legend wrapperStyle={legendStyle} />
              <Line
                type="monotone"
                dataKey="sleep_performance"
                name="Sleep performance %"
                stroke={CHART_COLORS.hrv}
                strokeWidth={2}
                dot={false}
                connectNulls
              />
              <Line
                type="monotone"
                dataKey="recovery_score"
                name="Recovery score"
                stroke={CHART_COLORS.recovery}
                strokeWidth={2}
                dot={false}
                connectNulls
              />
            </LineChart>
          </ResponsiveContainer>
        </ChartCard>
      )}
    </>
  );
}
