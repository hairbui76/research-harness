import React from "react";
import { Icon } from "./Icon.jsx";

const SIZES = { sm: 28, md: 34, lg: 40 };

export function IconButton({ name, size = "md", variant = "ghost", label, disabled = false, onClick, style, ...rest }) {
  const [hover, setHover] = React.useState(false);
  const [active, setActive] = React.useState(false);
  const box = SIZES[size] || SIZES.md;
  const solid = variant === "solid";
  const outlined = variant === "outlined";
  const on = hover && !disabled;
  return (
    <button
      type="button"
      aria-label={label || name}
      disabled={disabled}
      onClick={onClick}
      onMouseEnter={() => setHover(true)}
      onMouseLeave={() => { setHover(false); setActive(false); }}
      onMouseDown={() => setActive(true)}
      onMouseUp={() => setActive(false)}
      style={{
        display: "inline-flex", alignItems: "center", justifyContent: "center",
        width: box, height: box, padding: 0,
        borderRadius: "var(--radius-nav)",
        border: outlined ? "1px solid var(--border-default)" : "1px solid transparent",
        background: solid ? (on ? "var(--color-white)" : "var(--surface-inverse)") : on ? "var(--ink-10)" : "transparent",
        color: solid ? (on ? "var(--text-primary)" : "var(--text-inverse)") : "var(--text-secondary)",
        cursor: disabled ? "not-allowed" : "pointer",
        opacity: disabled ? 0.4 : 1,
        transform: active && !disabled ? "scale(var(--active-scale))" : "scale(1)",
        transition: "var(--transition-button)",
        ...style,
      }}
      {...rest}
    >
      <Icon name={name} size={Math.round(box * 0.5)} />
    </button>
  );
}
