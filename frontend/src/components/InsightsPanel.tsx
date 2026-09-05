import {
  Area,
  Bar,
  BarChart,
  CartesianGrid,
  Cell,
  Legend,
  Line,
  LineChart,
  ReferenceArea,
  ReferenceLine,
  ResponsiveContainer,
  Tooltip,
  XAxis,
  YAxis,
} from "recharts";
import type { InsightsResponse, DailyBriefResponse } from "../types";
import { isWithinDays, rewriteTriScaleCopy, shortDate } from "../utils";
import { ChartCard } from "./ChartCard";
import { DailyBriefCard } from "./DailyBriefCard";
import { Section } from "./Section";
import {
  AMBER,
  CHART_COLORS,
  axisLine,
  axisTick,
  gridStroke,
  guideStroke,
  legendStyle,
  tooltipStyle,
} from "../chartTheme";

const READ_ENTRY: Record<string, string> = {
  strain_recovery_lag: "strain_sensitivity",
  sleep_recovery: "stage_dependency",
  sleep_debt: "hyperarousal",
  training_readiness: "adaptation_window",
};

interface Props {
  insights: InsightsResponse;
  dailyBrief: DailyBriefResponse;
  rangeDays?: number;
  onOpenRead?: (id: string) => void;
}

export function InsightsPanel({ insights, dailyBrief, rangeDays, onOpenRead }: Props) {
  if (!insights.ready) {
    return (
      <Section id="insights" title="Insights">
        <DailyBriefCard brief={dailyBrief} />
        <ChartCard title="Derived insights">
          <p className="empty-chart">
            {rewriteTriScaleCopy(insights.message) || "Not enough data yet."}
          </p>
        </ChartCard>
      </Section>
    );
  }

  const sections = insights.sections ?? {};
  const inWindow = (iso: string) => (rangeDays == null ? true : isWithinDays(iso, rangeDays));
  const hrvSeries = (sections.hrv?.series ?? [])
    .filter((r) => inWindow(r.date))
    .map((r) => ({
      ...r,
      label: shortDate(r.date),
      bandLo: r.baseline * 0.9,
      bandSpan: r.baseline * 0.2,
    }));
  const acwrSeries = (sections.training_load?.series ?? [])
    .filter((r) => inWindow(r.date))
    .map((r) => ({
      ...r,
      label: shortDate(r.date),
    }));
  const sleepDebtSeries = (sections.sleep_debt?.series ?? [])
    .filter((r) => inWindow(r.date))
    .map((r) => ({
      ...r,
      label: shortDate(r.date),
    }));
  const weekday = sections.weekday_patterns?.by_weekday ?? [];
  const lagBuckets = sections.strain_recovery_lag?.buckets ?? [];
  const zonePct = sections.recovery_zones?.percentages;
  const rolling = (sections.rolling?.series ?? [])
    .filter((r) => inWindow(r.date))
    .map((r) => ({
      ...r,
      label: shortDate(r.date),
    }));

  return (
    <Section id="insights" title="Derived insights">
      <DailyBriefCard brief={dailyBrief} />

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
        {insights.cards.map((card) => {
          const readId = READ_ENTRY[card.id];
          const clickable = Boolean(readId && onOpenRead);
          return (
            <article
              key={card.id}
              className={`insight-card tone-${card.tone}${clickable ? " clickable" : ""}`}
              onClick={clickable ? () => onOpenRead?.(readId) : undefined}
              onKeyDown={
                clickable
                  ? (event) => {
                      if (event.key === "Enter" || event.key === " ") onOpenRead?.(readId);
                    }
                  : undefined
              }
              role={clickable ? "button" : undefined}
              tabIndex={clickable ? 0 : undefined}
            >
              <div className="insight-card-top">
                <span className="insight-status">{rewriteTriScaleCopy(card.status)}</span>
                <h3>{rewriteTriScaleCopy(card.title)}</h3>
              </div>
              <div className="insight-value">{rewriteTriScaleCopy(card.value)}</div>
              <div className="insight-sub">{rewriteTriScaleCopy(card.subtitle)}</div>
              <p>{rewriteTriScaleCopy(card.detail)}</p>
            </article>
          );
        })}
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
              <Area
                type="monotone"
                dataKey="bandLo"
                stackId="norm"
                stroke="none"
                fill="transparent"
                legendType="none"
                tooltipType="none"
              />
              <Area
                type="monotone"
                dataKey="bandSpan"
                stackId="norm"
                name="±10% of baseline"
                stroke="none"
                fill={AMBER}
                fillOpacity={0.08}
                legendType="none"
                tooltipType="none"
              />
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
                stroke={CHART_COLORS.amber}
                strokeWidth={2}
                strokeDasharray="5 5"
                dot={false}
              />
            </LineChart>
          </ResponsiveContainer>
          <p className="chart-footnote">30-day rolling mean of your own HRV · ±10% band around that mean.</p>
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
              <ReferenceArea y1={1.3} y2={1.5} fill={CHART_COLORS.amber} fillOpacity={0.07} />
              <ReferenceLine y={0.8} stroke={guideStroke} strokeDasharray="3 3" />
              <ReferenceLine y={1.3} stroke={guideStroke} strokeDasharray="3 3" />
              <ReferenceLine y={1.5} stroke={guideStroke} strokeDasharray="3 3" />
              <Line
                type="monotone"
                dataKey="acwr"
                name="ACWR"
                stroke={CHART_COLORS.amber}
                strokeWidth={2}
                dot={false}
              />
            </LineChart>
          </ResponsiveContainer>
          <p className="chart-footnote">Acute 7-day / chronic 28-day day-strain on your own cycles.</p>
        </ChartCard>
      )}

      {lagBuckets.length > 0 && (
        <ChartCard
          title="Next-day recovery by prior strain"
          description="All history · average recovery the day after low / medium / high strain."
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
          <p className="chart-footnote">All history · next-morning recovery after prior-day strain buckets on your cycles.</p>
        </ChartCard>
      )}

      {zonePct && (
        <ChartCard
          title="Recovery zone mix"
          description="All history · share of days by recovery score as an amber opacity ladder."
        >
          <ResponsiveContainer width="100%" height={260}>
            <BarChart
              data={[
                { zone: "a", pct: zonePct.red, fill: CHART_COLORS.recoveryLow },
                { zone: "b", pct: zonePct.yellow, fill: CHART_COLORS.recoveryMid },
                { zone: "c", pct: zonePct.green, fill: CHART_COLORS.recoveryHigh },
              ]}
              margin={{ top: 8, right: 12, left: 0, bottom: 0 }}
            >
              <CartesianGrid strokeDasharray="3 3" stroke={gridStroke} vertical={false} />
              <XAxis
                dataKey="zone"
                tick={false}
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
              <Tooltip
                contentStyle={tooltipStyle}
                labelFormatter={() => ""}
                formatter={(value) => [value, "% of days"]}
              />
              <Bar dataKey="pct" name="% of days" radius={[6, 6, 0, 0]}>
                <Cell fill={CHART_COLORS.recoveryLow} />
                <Cell fill={CHART_COLORS.recoveryMid} />
                <Cell fill={CHART_COLORS.recoveryHigh} />
              </Bar>
            </BarChart>
          </ResponsiveContainer>
          <ul className="stage-legend">
            <li>
              <span className="swatch" style={{ background: CHART_COLORS.recoveryLow }} />
              <em>{zonePct.red}%</em>
            </li>
            <li>
              <span className="swatch" style={{ background: CHART_COLORS.recoveryMid }} />
              <em>{zonePct.yellow}%</em>
            </li>
            <li>
              <span className="swatch" style={{ background: CHART_COLORS.recoveryHigh }} />
              <em>{zonePct.green}%</em>
            </li>
          </ul>
          <p className="chart-footnote">All history · share of your recovery scores as an amber opacity ladder.</p>
        </ChartCard>
      )}

      {weekday.length > 0 && (
        <ChartCard
          title="Weekday patterns"
          description={
            [
              "All history",
              sections.weekday_patterns?.best_recovery_day
                ? `Best recovery: ${sections.weekday_patterns.best_recovery_day}`
                : null,
              sections.weekday_patterns?.hardest_strain_day
                ? `Hardest strain: ${sections.weekday_patterns.hardest_strain_day}`
                : null,
            ]
              .filter(Boolean)
              .join(" · ") || "All history · average recovery and strain by day of week."
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
          <p className="chart-footnote">All history · average recovery and strain by weekday on your own cycles.</p>
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
          <p className="chart-footnote">WHOOP sleep_needed versus in-bed time on your scored nights.</p>
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
          <p className="chart-footnote">7-day rolling means of your recovery and day strain.</p>
        </ChartCard>
      )}

      {insights.disclaimer && (
        <p className="insight-disclaimer wide">{rewriteTriScaleCopy(insights.disclaimer)}</p>
      )}
    </Section>
  );
}
