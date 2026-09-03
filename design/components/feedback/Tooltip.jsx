import React from "react";

export function Tooltip({ content, children, placement = "top", style, ...rest }) {
  const [open, setOpen] = React.useState(false);
  const pos = placement === "bottom"
    ? { top: "calc(100% + 6px)", left: "50%", transform: "translateX(-50%)" }
    : { bottom: "calc(100% + 6px)", left: "50%", transform: "translateX(-50%)" };
  return (
    <span
      onMouseEnter={() => setOpen(true)} onMouseLeave={() => setOpen(false)}
      style={{ position: "relative", display: "inline-flex", ...style }} {...rest}
    >
      {children}
      {open && (
        <span style={{
          position: "absolute", ...pos, zIndex: 40, whiteSpace: "nowrap",
          background: "var(--surface-inverse)", color: "var(--text-inverse)",
          padding: "6px 8px", borderRadius: "var(--radius-button)",
          fontFamily: "var(--font-sans)", fontSize: "var(--type-body-sm-size)", fontWeight: 300, lineHeight: 1.4,
        }}>{content}</span>
      )}
    </span>
  );
}
