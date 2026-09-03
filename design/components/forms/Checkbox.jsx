import React from "react";
import { Icon } from "../core/Icon.jsx";

export function Checkbox({ label, checked, defaultChecked, onChange, disabled = false, style, ...rest }) {
  const [internal, setInternal] = React.useState(!!defaultChecked);
  const isOn = checked === undefined ? internal : checked;
  function toggle(e) {
    if (disabled) return;
    if (checked === undefined) setInternal(!isOn);
    if (onChange) onChange(!isOn, e);
  }
  return (
    <label style={{ display: "inline-flex", alignItems: "center", gap: 10, cursor: disabled ? "not-allowed" : "pointer", opacity: disabled ? 0.4 : 1, ...style }} {...rest}>
      <span
        onClick={toggle}
        style={{
          display: "inline-flex", alignItems: "center", justifyContent: "center",
          width: 18, height: 18, borderRadius: "var(--radius-button)",
          background: isOn ? "var(--surface-inverse)" : "var(--surface-primary)",
          border: "1px solid " + (isOn ? "var(--color-off-black)" : "var(--border-default)"),
          transition: "background-color var(--duration-fast) linear",
        }}
      >
        {isOn && <Icon name="check" size={12} color="var(--text-inverse)" />}
      </span>
      {label && <span style={{ fontFamily: "var(--font-sans)", fontSize: "var(--type-body-size)" }}>{label}</span>}
    </label>
  );
}
