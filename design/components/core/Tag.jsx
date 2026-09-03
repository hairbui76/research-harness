import React from "react";
import { Icon } from "./Icon.jsx";

export function Tag({ children, onRemove, selected = false, style, ...rest }) {
  return (
    <span
      style={{
        display: "inline-flex", alignItems: "center", gap: 6, height: 28, padding: "0 10px", whiteSpace: "nowrap",
        background: selected ? "var(--surface-inverse)" : "var(--surface-card)",
        color: selected ? "var(--text-inverse)" : "var(--text-primary)",
        border: `1px solid ${selected ? "var(--color-off-black)" : "var(--border-default)"}`,
        borderRadius: "var(--radius-button)",
        fontFamily: "var(--font-sans)", fontSize: "var(--type-body-sm-size)", fontWeight: 400,
        ...style,
      }}
      {...rest}
    >
      {children}
      {onRemove && (
        <button onClick={onRemove} aria-label="Remove" style={{ display: "inline-flex", padding: 0, border: 0, background: "none", cursor: "pointer", color: "inherit" }}>
          <Icon name="x" size={12} />
        </button>
      )}
    </span>
  );
}
