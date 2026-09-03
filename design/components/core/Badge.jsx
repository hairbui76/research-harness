import React from "react";

const TONES = {
  neutral: { bg: "var(--ink-10)", fg: "var(--text-primary)" },
  accent: { bg: "var(--color-fin)", fg: "var(--color-white)" },
  success: { bg: "var(--color-report-green)", fg: "var(--color-off-black)" },
  error: { bg: "var(--color-report-red)", fg: "var(--color-white)" },
  info: { bg: "var(--color-report-blue)", fg: "var(--color-off-black)" },
  inverse: { bg: "var(--surface-inverse)", fg: "var(--text-inverse)" },
};

export function Badge({ children, tone = "neutral", style, ...rest }) {
  const t = TONES[tone] || TONES.neutral;
  return (
    <span
      style={{
        display: "inline-flex", alignItems: "center", height: 20, padding: "0 6px",
        background: t.bg, color: t.fg,
        fontFamily: "var(--font-mono)", fontSize: "var(--type-mono-size)",
        lineHeight: 1, letterSpacing: "var(--type-mono-ls)", textTransform: "uppercase",
        borderRadius: "var(--radius-button)",
        ...style,
      }}
      {...rest}
    >
      {children}
    </span>
  );
}
