/** Shared Recharts styling — true-black + amber Mahath tokens. */

export const AMBER = "#FFC400";
export const AMBER_60 = "rgba(255,196,0,0.6)";
export const AMBER_35 = "rgba(255,196,0,0.35)";
export const AMBER_14 = "rgba(255,196,0,0.14)";
export const AMBER_08 = "rgba(255,196,0,0.08)";

export const CHART_COLORS = {
  recovery: AMBER,
  recoveryLow: AMBER_35,
  recoveryMid: AMBER_60,
  recoveryHigh: AMBER,
  strain: AMBER,
  sleep: AMBER_60,
  hrv: "#FFFFFF",
  rhr: AMBER,
  amber: AMBER,
  rose: AMBER_60,
  neutral: "#8A8A8A",
  out: "#666666",
};

export const gridStroke = "#2A2A2A";

export const axisTick = { fill: "#8A8A8A", fontSize: 11 };

export const axisLine = { stroke: "#333333" };

export const guideStroke = "#333333";

export const tooltipStyle = {
  background: "#1A1A1A",
  border: "1px solid #333333",
  borderRadius: 16,
  color: "#FFFFFF",
  fontSize: 12,
  boxShadow: "0 2px 12px rgba(0,0,0,.5)",
};

export const legendStyle = { fontSize: 12, color: "#8A8A8A" };
