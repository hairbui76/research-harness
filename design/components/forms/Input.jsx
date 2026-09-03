import React from "react";
import { Icon } from "../core/Icon.jsx";

export function Input({ label, hint, error, iconLeft, size = "md", style, id, ...rest }) {
  const [focus, setFocus] = React.useState(false);
  const inputId = id || (label ? "in-" + String(label).toLowerCase().replace(/[^a-z0-9]+/g, "-") : undefined);
  const height = size === "sm" ? 32 : 40;
  return (
    <div style={{ display: "flex", flexDirection: "column", gap: 8, ...style }}>
      {label && (
        <label htmlFor={inputId} style={{ fontFamily: "var(--font-mono)", fontSize: "var(--type-mono-size)", letterSpacing: "var(--type-mono-ls)", textTransform: "uppercase", color: "var(--text-muted)" }}>{label}</label>
      )}
      <div style={{
        display: "flex", alignItems: "center", gap: 8, height, padding: "0 12px",
        background: "var(--surface-primary)",
        border: "1px solid " + (error ? "var(--feedback-error)" : focus ? "var(--border-strong)" : "var(--border-default)"),
        borderRadius: "var(--radius-button)",
        transition: "border-color var(--duration-fast) linear",
      }}>
        {iconLeft && <Icon name={iconLeft} size={16} color="var(--text-muted)" />}
        <input
          id={inputId}
          onFocus={() => setFocus(true)}
          onBlur={() => setFocus(false)}
          style={{
            flex: 1, minWidth: 0, height: "100%", border: 0, outline: "none", background: "transparent",
            fontFamily: "var(--font-sans)", fontSize: size === "sm" ? "var(--type-body-sm-size)" : "var(--type-body-size)",
            color: "var(--text-primary)",
          }}
          {...rest}
        />
      </div>
      {(error || hint) && (
        <span style={{ fontFamily: "var(--font-sans)", fontSize: "var(--type-body-sm-size)", fontWeight: 300, color: error ? "var(--feedback-error)" : "var(--text-muted)" }}>{error || hint}</span>
      )}
    </div>
  );
}
