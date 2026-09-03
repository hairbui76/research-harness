import React from "react";

export function Switch({ label, checked, defaultChecked, onChange, disabled = false, style, ...rest }) {
  const [internal, setInternal] = React.useState(!!defaultChecked);
  const isOn = checked === undefined ? internal : checked;
  function toggle() {
    if (disabled) return;
    if (checked === undefined) setInternal(!isOn);
    if (onChange) onChange(!isOn);
  }
  return (
    <label style={{ display: "inline-flex", alignItems: "center", gap: 10, cursor: disabled ? "not-allowed" : "pointer", opacity: disabled ? 0.4 : 1, ...style }} {...rest}>
      <span
        role="switch" aria-checked={isOn} onClick={toggle}
        style={{
          position: "relative", display: "inline-block", width: 36, height: 20,
          borderRadius: "var(--radius-button)",
          background: isOn ? "var(--surface-inverse)" : "var(--color-sand)",
          border: "1px solid " + (isOn ? "var(--color-off-black)" : "var(--border-default)"),
          transition: "background-color var(--duration-base) linear",
        }}
      >
        <span style={{
          position: "absolute", top: 2, left: isOn ? 18 : 2, width: 14, height: 14,
          borderRadius: 2, background: "var(--color-white)",
          transition: "left var(--duration-base) var(--ease-standard)",
        }} />
      </span>
      {label && <span style={{ fontFamily: "var(--font-sans)", fontSize: "var(--type-body-size)" }}>{label}</span>}
    </label>
  );
}
