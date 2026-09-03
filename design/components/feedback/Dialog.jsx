import React from "react";
import { IconButton } from "../core/IconButton.jsx";

export function Dialog({ open = false, title, description, children, footer, onClose, width = 440, style, ...rest }) {
  if (!open) return null;
  return (
    <div
      style={{ position: "fixed", inset: 0, zIndex: 60, display: "flex", alignItems: "center", justifyContent: "center", background: "var(--ink-30)", backdropFilter: "blur(2px)" }}
      onClick={onClose}
    >
      <div
        role="dialog" aria-modal="true" onClick={(e) => e.stopPropagation()}
        style={{
          width, maxWidth: "calc(100vw - 32px)", padding: 24,
          background: "var(--surface-primary)", border: "1px solid var(--border-default)",
          borderRadius: "var(--radius-card)", ...style,
        }}
        {...rest}
      >
        <div style={{ display: "flex", alignItems: "flex-start", gap: 16, justifyContent: "space-between" }}>
          <div>
            <h4 style={{ margin: 0, fontFamily: "var(--font-sans)", fontSize: "var(--type-h4-size)", lineHeight: 1, letterSpacing: "var(--type-h4-ls)", fontWeight: 400 }}>{title}</h4>
            {description && <p style={{ margin: "10px 0 0", fontSize: "var(--type-body-size)", color: "var(--text-muted)" }}>{description}</p>}
          </div>
          {onClose && <IconButton name="x" size="sm" label="Close" onClick={onClose} />}
        </div>
        {children && <div style={{ marginTop: 20 }}>{children}</div>}
        {footer && <div style={{ display: "flex", justifyContent: "flex-end", gap: 8, marginTop: 24 }}>{footer}</div>}
      </div>
    </div>
  );
}
