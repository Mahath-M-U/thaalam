/**
 * Shared Recharts tokens, per docs/design.md.
 *
 * The system has no saturated accent, so data is encoded in the ink ladder:
 * severity reads as distance from your own band, never as hue. The pastel
 * gradient stops are atmosphere only -- they may fill an area or a baseline
 * band, but they never carry a stroke, a dot, or a text colour.
 */

export const INK = "#0c0a09";
export const INK_60 = "rgba(12,10,9,0.6)";
export const INK_35 = "rgba(12,10,9,0.35)";
export const INK_14 = "rgba(12,10,9,0.14)";
export const INK_08 = "rgba(12,10,9,0.08)";

export const MUTED = "#736d65";
export const MUTED_SOFT = "#a8a29e";
export const SURFACE_CARD = "#ffffff";

/**
 * Atmospheric washes. Own-baseline bands, projection cones, optimal-zone
 * shading and single-series area fills only -- never a stroke, a dot, or a
 * categorical encoding. Pre-alpha'd so they drop straight into `fill`.
 */
export const WASH_MINT = "rgba(167,229,211,0.45)";
export const WASH_LAVENDER = "rgba(200,184,224,0.40)";
export const WASH_PEACH = "rgba(244,197,168,0.40)";
export const WASH_SKY = "rgba(168,200,232,0.40)";
export const WASH_ROSE = "rgba(232,184,196,0.40)";

export const CHART_COLORS = {
  recovery: INK,
  recoveryLow: INK_35,
  recoveryMid: INK_60,
  recoveryHigh: INK,
  strain: MUTED,
  sleep: INK_60,
  hrv: MUTED,
  rhr: INK,
  ink: INK,
  wash: WASH_MINT,
  neutral: MUTED_SOFT,
  out: "#d6d3d1",
};

export const gridStroke = "#e7e5e4";

export const axisTick = { fill: "#736d65", fontSize: 11 };

export const axisLine = { stroke: "#d6d3d1" };

export const guideStroke = "#d6d3d1";

export const tooltipStyle = {
  background: SURFACE_CARD,
  border: "1px solid #e7e5e4",
  borderRadius: 16,
  color: INK,
  fontSize: 12,
  boxShadow: "0 4px 16px rgba(0,0,0,0.04)",
};

export const legendStyle = { fontSize: 12, color: "#736d65" };
