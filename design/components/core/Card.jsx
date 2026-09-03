import React from "react";

export function Card({ children, padding = 24, tone = "cream", interactive = false, style, ...rest }) {
  const [hover, setHover] = React.useState(false);
  const bg = tone === "white" ? "var(--surface-primary)" : tone === "inverse" ? "var(--surface-inverse)" : "var(--surface-card)";
  return (
    <div
      onMouseEnter={interactive ? () => setHover(true) : undefined}
      onMouseLeave={interactive ? () => setHover(false) : undefined}
      style={{
        background: bg,
        color: tone === "inverse" ? "var(--text-inverse)" : "var(--text-primary)",
        border: `1px solid ${tone === "inverse" ? "var(--color-off-black)" : "var(--border-default)"}`,
        borderRadius: "var(--radius-card)",
        padding,
        boxShadow: "var(--shadow-card)",
        transition: "border-color var(--duration-base) linear, background-color var(--duration-base) linear",
        borderColor: hover ? "var(--border-strong)" : undefined,
        cursor: interactive ? "pointer" : undefined,
        ...style,
      }}
      {...rest}
    >
      {children}
    </div>
  );
}
