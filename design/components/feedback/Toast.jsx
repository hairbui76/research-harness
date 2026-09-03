import React from "react";
import { Icon } from "../core/Icon.jsx";

const ICONS = { neutral: "info", success: "check-circle", error: "alert-circle", info: "info" };

export function Toast({ title, description, tone = "neutral", onDismiss, style, ...rest }) {
  const accent = tone === "success" ? "var(--feedback-success)" : tone === "error" ? "var(--feedback-error)" : tone === "info" ? "var(--feedback-info)" : "var(--color-fin)";
  return (
    <div style={{
      display: "flex", alignItems: "flex-start", gap: 12, width: 340, padding: 16,
      background: "var(--surface-inverse)", color: "var(--text-inverse)",
      border: "1px solid var(--color-off-black)", borderRadius: "var(--radius-card)",
      ...style,
    }} {...rest}>
      <Icon name={ICONS[tone] || "info"} size={18} color={accent} style={{ marginTop: 1 }} />
      <div style={{ flex: 1, minWidth: 0 }}>
        <div style={{ fontFamily: "var(--font-sans)", fontSize: "var(--type-body-size)", letterSpacing: "-0.1px" }}>{title}</div>
        {description && <div style={{ marginTop: 4, fontFamily: "var(--font-sans)", fontSize: "var(--type-body-sm-size)", fontWeight: 300, color: "var(--color-sand)" }}>{description}</div>}
      </div>
      {onDismiss && (
        <button onClick={onDismiss} aria-label="Dismiss" style={{ display: "inline-flex", border: 0, background: "none", padding: 0, cursor: "pointer", color: "var(--color-sand)" }}>
          <Icon name="x" size={14} />
        </button>
      )}
    </div>
  );
}
