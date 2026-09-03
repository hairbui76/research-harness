import React from "react";

const SIZES = {
  md: { height: 40, padding: "0 14px", fontSize: "var(--type-button-size)", lineHeight: "var(--type-button-lh)", gap: 8 },
  sm: { height: 32, padding: "0 12px", fontSize: "var(--type-button-sm-size)", lineHeight: "var(--type-button-sm-lh)", gap: 6 },
  lg: { height: 48, padding: "0 20px", fontSize: "var(--type-button-size)", lineHeight: "var(--type-button-lh)", gap: 10 },
};

function palette(variant) {
  switch (variant) {
    case "outlined":
      return { bg: "transparent", fg: "var(--text-primary)", border: "1px solid var(--border-strong)", hoverBg: "var(--surface-inverse)", hoverFg: "var(--text-inverse)" };
    case "warm":
      return { bg: "var(--surface-card)", fg: "var(--text-primary)", border: "1px solid var(--border-subtle)", hoverBg: "var(--color-white)", hoverFg: "var(--text-primary)" };
    case "accent":
      return { bg: "var(--button-accent-bg)", fg: "var(--button-accent-fg)", border: "1px solid transparent", hoverBg: "var(--color-white)", hoverFg: "var(--color-fin)" };
    case "ghost":
      return { bg: "transparent", fg: "var(--text-primary)", border: "1px solid transparent", hoverBg: "var(--ink-10)", hoverFg: "var(--text-primary)" };
    default:
      return { bg: "var(--button-primary-bg)", fg: "var(--button-primary-fg)", border: "1px solid var(--border-strong)", hoverBg: "var(--button-primary-bg-hover)", hoverFg: "var(--button-primary-fg-hover)" };
  }
}

export function Button({ variant = "primary", size = "md", children, disabled = false, fullWidth = false, href, onClick, type = "button", style, ...rest }) {
  const [hover, setHover] = React.useState(false);
  const [active, setActive] = React.useState(false);
  const s = SIZES[size] || SIZES.md;
  const p = palette(variant);
  const on = hover && !disabled;

  const css = {
    display: fullWidth ? "flex" : "inline-flex",
    width: fullWidth ? "100%" : undefined,
    alignItems: "center",
    justifyContent: "center",
    gap: s.gap,
    height: s.height,
    padding: s.padding,
    fontFamily: "var(--font-sans)",
    fontSize: s.fontSize,
    lineHeight: s.lineHeight,
    fontWeight: 400,
    borderRadius: "var(--radius-button)",
    border: p.border,
    background: active && !disabled ? "var(--button-primary-bg-active)" : on ? p.hoverBg : p.bg,
    color: active && !disabled ? "var(--text-inverse)" : on ? p.hoverFg : p.fg,
    cursor: disabled ? "not-allowed" : "pointer",
    opacity: disabled ? 0.4 : 1,
    transform: active && !disabled ? "scale(var(--active-scale))" : on ? "scale(var(--hover-scale))" : "scale(1)",
    transition: "var(--transition-button)",
    textDecoration: "none",
    whiteSpace: "nowrap",
    ...style,
  };

  const handlers = {
    onMouseEnter: () => setHover(true),
    onMouseLeave: () => { setHover(false); setActive(false); },
    onMouseDown: () => setActive(true),
    onMouseUp: () => setActive(false),
  };

  if (href && !disabled) return <a href={href} style={css} {...handlers} {...rest}>{children}</a>;
  return <button type={type} disabled={disabled} onClick={onClick} style={css} {...handlers} {...rest}>{children}</button>;
}
