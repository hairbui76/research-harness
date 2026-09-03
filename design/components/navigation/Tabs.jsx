import React from "react";

export function Tabs({ items = [], value, defaultValue, onChange, style, ...rest }) {
  const first = items.length ? (typeof items[0] === "string" ? items[0] : items[0].value) : undefined;
  const [internal, setInternal] = React.useState(defaultValue !== undefined ? defaultValue : first);
  const active = value === undefined ? internal : value;
  return (
    <div role="tablist" style={{ display: "flex", alignItems: "center", gap: 4, borderBottom: "1px solid var(--border-default)", ...style }} {...rest}>
      {items.map(function (it) {
        const t = typeof it === "string" ? { value: it, label: it } : it;
        const on = t.value === active;
        return (
          <button
            key={t.value} role="tab" aria-selected={on}
            onClick={function () { if (value === undefined) setInternal(t.value); if (onChange) onChange(t.value); }}
            style={{
              display: "inline-flex", alignItems: "center", gap: 6, height: 36, padding: "0 10px",
              border: 0, background: "transparent", cursor: "pointer",
              fontFamily: "var(--font-sans)", fontSize: "var(--type-body-size)",
              color: on ? "var(--text-primary)" : "var(--text-muted)",
              borderBottom: "2px solid " + (on ? "var(--color-off-black)" : "transparent"),
              marginBottom: -1,
              transition: "color var(--duration-fast) linear",
            }}
          >
            {t.label}
            {t.count !== undefined && (
              <span style={{ fontFamily: "var(--font-mono)", fontSize: "var(--type-mono-size)", color: "var(--text-tertiary)" }}>{t.count}</span>
            )}
          </button>
        );
      })}
    </div>
  );
}
