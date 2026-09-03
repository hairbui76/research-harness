import React from "react";
import { Icon } from "../core/Icon.jsx";

export function Select({ label, options = [], value, onChange, size = "md", style, id, ...rest }) {
  const [focus, setFocus] = React.useState(false);
  const height = size === "sm" ? 32 : 40;
  return (
    <div style={{ display: "flex", flexDirection: "column", gap: 8, ...style }}>
      {label && <label htmlFor={id} style={{ fontFamily: "var(--font-mono)", fontSize: "var(--type-mono-size)", letterSpacing: "var(--type-mono-ls)", textTransform: "uppercase", color: "var(--text-muted)" }}>{label}</label>}
      <div style={{ position: "relative", display: "flex", alignItems: "center" }}>
        <select
          id={id} value={value} onChange={onChange}
          onFocus={() => setFocus(true)} onBlur={() => setFocus(false)}
          style={{
            appearance: "none", width: "100%", height, padding: "0 34px 0 12px",
            background: "var(--surface-primary)", color: "var(--text-primary)",
            border: "1px solid " + (focus ? "var(--border-strong)" : "var(--border-default)"),
            borderRadius: "var(--radius-button)", outline: "none",
            fontFamily: "var(--font-sans)", fontSize: size === "sm" ? "var(--type-body-sm-size)" : "var(--type-body-size)",
          }}
          {...rest}
        >
          {options.map(function (o) {
            const opt = typeof o === "string" ? { value: o, label: o } : o;
            return <option key={opt.value} value={opt.value}>{opt.label}</option>;
          })}
        </select>
        <Icon name="chevron-down" size={16} color="var(--text-muted)" style={{ position: "absolute", right: 12, pointerEvents: "none" }} />
      </div>
    </div>
  );
}
