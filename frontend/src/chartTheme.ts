/** Shared Recharts styling so every chart matches the light editorial theme (see docs/design.md). */

export const CHART_COLORS = {
  recovery: "#16a34a",
  recoveryLow: "#dc2626",
  recoveryMid: "#d97706",
  recoveryHigh: "#16a34a",
  strain: "#3f7ca8",
  sleep: "#8868b8",
  hrv: "#2f9e6e",
  rhr: "#c2607a",
  amber: "#c9793f",
  rose: "#c2607a",
  neutral: "#a8a29e",
};

export const gridStroke = "#e7e5e4";

export const axisTick = { fill: "#a8a29e", fontSize: 11 };

export const axisLine = { stroke: "#d6d3d1" };

export const tooltipStyle = {
  background: "#ffffff",
  border: "1px solid #e7e5e4",
  borderRadius: 12,
  color: "#0c0a09",
  fontSize: 12,
  boxShadow: "0 4px 16px rgba(12, 10, 9, 0.08)",
};

export const legendStyle = { fontSize: 12, color: "#777169" };
