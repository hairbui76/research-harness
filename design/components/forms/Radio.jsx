import React from "react";

export function Radio({ label, checked, name, value, onChange, disabled = false, style, ...rest }) {
  return (
    <label style={{ display: "inline-flex", alignItems: "center", gap: 10, cursor: disabled ? "not-allowed" : "pointer", opacity: disabled ? 0.4 : 1, ...style }} {...rest}>
      <span style={{
        display: "inline-flex", alignItems: "center", justifyContent: "center",
        width: 18, height: 18, borderRadius: "var(--radius-pill)",
        background: "var(--surface-primary)",
        border: "1px solid " + (checked ? "var(--color-off-black)" : "var(--border-default)"),
      }}>
        {checked && <span style={{ width: 8, height: 8, borderRadius: "var(--radius-pill)", background: "var(--surface-inverse)" }} />}
      </span>
      <input type="radio" name={name} value={value} checked={!!checked} onChange={onChange} disabled={disabled} style={{ position: "absolute", opacity: 0, width: 0, height: 0 }} />
      {label && <span style={{ fontFamily: "var(--font-sans)", fontSize: "var(--type-body-size)" }}>{label}</span>}
    </label>
  );
}
