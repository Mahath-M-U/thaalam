import {
  Bar,
  BarChart,
  CartesianGrid,
  Cell,
  Legend,
  Line,
  LineChart,
  ReferenceLine,
  ResponsiveContainer,
  Tooltip,
  XAxis,
  YAxis,
} from "recharts";
import type { InsightsResponse } from "../types";
import { shortDate } from "../utils";
import { ChartCard } from "./ChartCard";
import { Section } from "./Section";
import { CHART_COLORS, axisLine, axisTick, gridStroke, legendStyle, tooltipStyle } from "../chartTheme";

interface Props {
  insights: InsightsResponse;
}

export function InsightsPanel({ insights }: Props) {
  if (!insights.ready) {
    return (
      <Section id="insights" title="Insights" accent={CHART_COLORS.rose}>
        <ChartCard title="Derived insights">
          <p className="empty-chart">{insights.message ?? "Not enough data yet."}</p>
        </ChartCard>
      </Section>
    );
  }

  const sections = insights.sections ?? {};
  const hrvSeries = (sections.hrv?.series ?? []).map((r) => ({
    ...r,
    label: shortDate(r.date),
  }));
  const acwrSeries = (sections.training_load?.series ?? []).map((r) => ({
    ...r,
    label: shortDate(r.date),
  }));
  const sleepDebtSeries = (sections.sleep_debt?.series ?? []).map((r) => ({
    ...r,
    label: shortDate(r.date),
  }));
  const weekday = sections.weekday_patterns?.by_weekday ?? [];
  const lagBuckets = sections.strain_recovery_lag?.buckets ?? [];
  const zonePct = sections.recovery_zones?.percentages;
  const rolling = (sections.rolling?.series ?? []).map((r) => ({
    ...r,
    label: shortDate(r.date),
  }));

  return (
    <Section id="insights" title="Derived insights" accent={CHART_COLORS.rose}>
      <div className="insight-meta wide">
        <p>
          Built from <strong>{insights.generated_from_days}</strong> days
          {insights.date_range
            ? ` (${insights.date_range.start} → ${insights.date_range.end})`
            : ""}
          . Personalized baselines, load ratios, and lag effects from your local
          WHOOP history.
        </p>
      </div>

      <div className="insight-cards wide">
        {insights.cards.map((card) => (
          <article key={card.id} className={`insight-card tone-${card.tone}`}>
            <div className="insight-card-top">
              <span className="insight-status">{card.status}</span>
              <h3>{card.title}</h3>
            </div>
            <div className="insight-value">{card.value}</div>
            <div className="insight-sub">{card.subtitle}</div>
            <p>{card.detail}</p>
          </article>
        ))}
      </div>

      {hrvSeries.length > 0 && (
        <ChartCard
          title="HRV vs 30-day personal baseline"
          description="Single HRV readings mean more when compared to your own rolling baseline (±10–15% is notable)."
          wide
        >
          <ResponsiveContainer width="100%" height={280}>
            <LineChart data={hrvSeries} margin={{ top: 8, right: 12, left: 0, bottom: 0 }}>
              <CartesianGrid strokeDasharray="3 3" stroke={gridStroke} vertical={false} />
              <XAxis
                dataKey="label"
                tick={axisTick}
                axisLine={axisLine}
                tickLine={false}
                minTickGap={32}
              />
              <YAxis
                tick={axisTick}
                axisLine={false}
                tickLine={false}
                width={40}
              />
              <Tooltip contentStyle={tooltipStyle} />
              <Legend wrapperStyle={legendStyle} />
              <Line
                type="monotone"
                dataKey="hrv"
                name="HRV (ms)"
                stroke={CHART_COLORS.hrv}
                strokeWidth={2}
                dot={false}
              />
              <Line
                type="monotone"
                dataKey="baseline"
                name="30d baseline"
                stroke={CHART_COLORS.neutral}
                strokeWidth={2}
                strokeDasharray="5 5"
                dot={false}
              />
            </LineChart>
          </ResponsiveContainer>
        </ChartCard>
      )}

      {acwrSeries.length > 0 && (
        <ChartCard
          title="Training load ratio (acute 7d / chronic 28d)"
          description="ACWR-style ratio on day strain. Common bands: sweet spot ~0.8–1.3; spikes &gt;1.5 often flagged."
          wide
        >
          <ResponsiveContainer width="100%" height={280}>
            <LineChart data={acwrSeries} margin={{ top: 8, right: 12, left: 0, bottom: 0 }}>
              <CartesianGrid strokeDasharray="3 3" stroke={gridStroke} vertical={false} />
              <XAxis
                dataKey="label"
                tick={axisTick}
                axisLine={axisLine}
                tickLine={false}
                minTickGap={32}
              />
              <YAxis
                tick={axisTick}
                axisLine={false}
                tickLine={false}
                width={40}
                domain={["auto", "auto"]}
              />
              <Tooltip contentStyle={tooltipStyle} />
              <ReferenceLine y={0.8} stroke={CHART_COLORS.neutral} strokeDasharray="3 3" />
              <ReferenceLine y={1.3} stroke={CHART_COLORS.amber} strokeDasharray="3 3" />
              <ReferenceLine y={1.5} stroke={CHART_COLORS.recoveryLow} strokeDasharray="3 3" />
              <Line
                type="monotone"
                dataKey="acwr"
                name="ACWR"
                stroke={CHART_COLORS.strain}
                strokeWidth={2}
                dot={false}
              />
            </LineChart>
          </ResponsiveContainer>
        </ChartCard>
      )}

      {lagBuckets.length > 0 && (
        <ChartCard
          title="Next-day recovery by prior strain"
          description="Average recovery the day after low / medium / high strain."
        >
          <ResponsiveContainer width="100%" height={260}>
            <BarChart data={lagBuckets} margin={{ top: 8, right: 12, left: 0, bottom: 0 }}>
              <CartesianGrid strokeDasharray="3 3" stroke={gridStroke} vertical={false} />
              <XAxis
                dataKey="prior_strain"
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
              <Bar
                dataKey="avg_next_recovery"
                name="Avg next recovery"
                fill={CHART_COLORS.sleep}
                radius={[6, 6, 0, 0]}
              />
            </BarChart>
          </ResponsiveContainer>
        </ChartCard>
      )}

      {zonePct && (
        <ChartCard
          title="Recovery zone mix"
          description="Share of days in WHOOP-style red / yellow / green bands."
        >
          <ResponsiveContainer width="100%" height={260}>
            <BarChart
              data={[
                { zone: "Red", pct: zonePct.red, fill: CHART_COLORS.recoveryLow },
                { zone: "Yellow", pct: zonePct.yellow, fill: CHART_COLORS.recoveryMid },
                { zone: "Green", pct: zonePct.green, fill: CHART_COLORS.recoveryHigh },
              ]}
              margin={{ top: 8, right: 12, left: 0, bottom: 0 }}
            >
              <CartesianGrid strokeDasharray="3 3" stroke={gridStroke} vertical={false} />
              <XAxis
                dataKey="zone"
                tick={axisTick}
                axisLine={axisLine}
                tickLine={false}
              />
              <YAxis
                unit="%"
                tick={axisTick}
                axisLine={false}
                tickLine={false}
                width={40}
              />
              <Tooltip contentStyle={tooltipStyle} />
              <Bar dataKey="pct" name="% of days" radius={[6, 6, 0, 0]}>
                <Cell fill={CHART_COLORS.recoveryLow} />
                <Cell fill={CHART_COLORS.recoveryMid} />
                <Cell fill={CHART_COLORS.recoveryHigh} />
              </Bar>
            </BarChart>
          </ResponsiveContainer>
          <ul className="stage-legend">
            <li>
              <span className="swatch" style={{ background: CHART_COLORS.recoveryLow }} /> Red{" "}
              <em>{zonePct.red}%</em>
            </li>
            <li>
              <span className="swatch" style={{ background: CHART_COLORS.recoveryMid }} /> Yellow{" "}
              <em>{zonePct.yellow}%</em>
            </li>
            <li>
              <span className="swatch" style={{ background: CHART_COLORS.recoveryHigh }} /> Green{" "}
              <em>{zonePct.green}%</em>
            </li>
          </ul>
        </ChartCard>
      )}

      {weekday.length > 0 && (
        <ChartCard
          title="Weekday patterns"
          description={
            [
              sections.weekday_patterns?.best_recovery_day
                ? `Best recovery: ${sections.weekday_patterns.best_recovery_day}`
                : null,
              sections.weekday_patterns?.hardest_strain_day
                ? `Hardest strain: ${sections.weekday_patterns.hardest_strain_day}`
                : null,
            ]
              .filter(Boolean)
              .join(" · ") || "Average recovery and strain by day of week."
          }
          wide
        >
          <ResponsiveContainer width="100%" height={280}>
            <BarChart data={weekday} margin={{ top: 8, right: 12, left: 0, bottom: 0 }}>
              <CartesianGrid strokeDasharray="3 3" stroke={gridStroke} vertical={false} />
              <XAxis
                dataKey="weekday"
                tick={axisTick}
                axisLine={axisLine}
                tickLine={false}
                tickFormatter={(v: string) => v.slice(0, 3)}
              />
              <YAxis
                yAxisId="rec"
                domain={[0, 100]}
                tick={{ fill: CHART_COLORS.recovery, fontSize: 11 }}
                axisLine={false}
                tickLine={false}
                width={36}
              />
              <YAxis
                yAxisId="strain"
                orientation="right"
                tick={{ fill: CHART_COLORS.strain, fontSize: 11 }}
                axisLine={false}
                tickLine={false}
                width={36}
              />
              <Tooltip contentStyle={tooltipStyle} />
              <Legend wrapperStyle={legendStyle} />
              <Bar
                yAxisId="rec"
                dataKey="avg_recovery"
                name="Avg recovery"
                fill={CHART_COLORS.recovery}
                radius={[4, 4, 0, 0]}
              />
              <Bar
                yAxisId="strain"
                dataKey="avg_strain"
                name="Avg strain"
                fill={CHART_COLORS.strain}
                radius={[4, 4, 0, 0]}
              />
            </BarChart>
          </ResponsiveContainer>
        </ChartCard>
      )}

      {sleepDebtSeries.length > 0 && (
        <ChartCard
          title="Sleep need vs time in bed"
          description="Debt-driven need from WHOOP sleep_needed, compared with in-bed time when available."
          wide
        >
          <ResponsiveContainer width="100%" height={280}>
            <LineChart data={sleepDebtSeries} margin={{ top: 8, right: 12, left: 0, bottom: 0 }}>
              <CartesianGrid strokeDasharray="3 3" stroke={gridStroke} vertical={false} />
              <XAxis
                dataKey="label"
                tick={axisTick}
                axisLine={axisLine}
                tickLine={false}
                minTickGap={32}
              />
              <YAxis
                tick={axisTick}
                axisLine={false}
                tickLine={false}
                width={36}
                unit="h"
              />
              <Tooltip contentStyle={tooltipStyle} />
              <Legend wrapperStyle={legendStyle} />
              <Line
                type="monotone"
                dataKey="need_hours"
                name="Need (h)"
                stroke={CHART_COLORS.sleep}
                strokeWidth={2}
                dot={false}
              />
              <Line
                type="monotone"
                dataKey="in_bed_hours"
                name="In bed (h)"
                stroke={CHART_COLORS.strain}
                strokeWidth={2}
                dot={false}
                connectNulls
              />
              <Line
                type="monotone"
                dataKey="debt_hours"
                name="Debt component (h)"
                stroke={CHART_COLORS.recoveryLow}
                strokeWidth={1.5}
                strokeDasharray="4 4"
                dot={false}
              />
            </LineChart>
          </ResponsiveContainer>
        </ChartCard>
      )}

      {rolling.length > 0 && (
        <ChartCard
          title="7-day rolling recovery & strain"
          description="Smoothed trends — weekly averages reduce day-to-day noise."
          wide
        >
          <ResponsiveContainer width="100%" height={280}>
            <LineChart data={rolling} margin={{ top: 8, right: 12, left: 0, bottom: 0 }}>
              <CartesianGrid strokeDasharray="3 3" stroke={gridStroke} vertical={false} />
              <XAxis
                dataKey="label"
                tick={axisTick}
                axisLine={axisLine}
                tickLine={false}
                minTickGap={32}
              />
              <YAxis
                yAxisId="rec"
                domain={[0, 100]}
                tick={{ fill: CHART_COLORS.recovery, fontSize: 11 }}
                axisLine={false}
                tickLine={false}
                width={36}
              />
              <YAxis
                yAxisId="strain"
                orientation="right"
                tick={{ fill: CHART_COLORS.strain, fontSize: 11 }}
                axisLine={false}
                tickLine={false}
                width={36}
              />
              <Tooltip contentStyle={tooltipStyle} />
              <Legend wrapperStyle={legendStyle} />
              <Line
                yAxisId="rec"
                type="monotone"
                dataKey="recovery_7d"
                name="Recovery 7d avg"
                stroke={CHART_COLORS.recovery}
                strokeWidth={2}
                dot={false}
                connectNulls
              />
              <Line
                yAxisId="strain"
                type="monotone"
                dataKey="strain_7d"
                name="Strain 7d avg"
                stroke={CHART_COLORS.strain}
                strokeWidth={2}
                dot={false}
                connectNulls
              />
            </LineChart>
          </ResponsiveContainer>
        </ChartCard>
      )}

      {insights.disclaimer && (
        <p className="insight-disclaimer wide">{insights.disclaimer}</p>
      )}
    </Section>
  );
}
