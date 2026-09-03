// Helpdesk app chrome: left icon rail, workspace header, section title bar.
const RAIL = [
  { id: "inbox", icon: "inbox", label: "Inbox", count: 12 },
  { id: "reports", icon: "bar-chart-3", label: "Reports" },
  { id: "settings", icon: "settings", label: "Settings" },
];

function Rail({ route, onRoute, onSignOut }) {
  return (
    <aside style={{ width: 64, flex: "0 0 64px", background: "var(--surface-inverse)", display: "flex", flexDirection: "column", alignItems: "center", padding: "16px 0", gap: 8 }}>
      <div style={{ width: 32, height: 32, borderRadius: "var(--radius-button)", background: "var(--color-fin)", display: "flex", alignItems: "center", justifyContent: "center", color: "#fff", fontFamily: "var(--font-sans)", fontSize: 18, lineHeight: 1, marginBottom: 12 }}>W</div>
      {RAIL.map((r) => {
        const on = route === r.id;
        return (
          <Tooltip key={r.id} content={r.label} placement="bottom">
            <button onClick={() => onRoute(r.id)} aria-label={r.label}
              style={{ position: "relative", width: 40, height: 40, display: "flex", alignItems: "center", justifyContent: "center", borderRadius: "var(--radius-nav)", border: 0, cursor: "pointer", background: on ? "var(--color-black-80)" : "transparent" }}>
              <Icon name={r.icon} size={20} color={on ? "#fff" : "var(--color-black-50)"} />
              {r.count && <span style={{ position: "absolute", top: 4, right: 2, minWidth: 16, height: 16, padding: "0 4px", borderRadius: 999, background: "var(--color-fin)", color: "#fff", fontFamily: "var(--font-mono)", fontSize: 10, lineHeight: "16px", textAlign: "center" }}>{r.count}</span>}
            </button>
          </Tooltip>
        );
      })}
      <div style={{ marginTop: "auto", display: "flex", flexDirection: "column", gap: 8, alignItems: "center" }}>
        <Tooltip content="Sign out" placement="top">
          <button onClick={onSignOut} aria-label="Sign out" style={{ width: 40, height: 40, display: "flex", alignItems: "center", justifyContent: "center", borderRadius: "var(--radius-nav)", border: 0, background: "transparent", cursor: "pointer" }}>
            <Icon name="log-out" size={18} color="var(--color-black-50)" />
          </button>
        </Tooltip>
        <div style={{ width: 28, height: 28, borderRadius: 999, background: "var(--color-sand)", display: "flex", alignItems: "center", justifyContent: "center", fontFamily: "var(--font-sans)", fontSize: 12 }}>DO</div>
      </div>
    </aside>
  );
}

function PanelHead({ title, children, right }) {
  return (
    <div style={{ height: 56, flex: "0 0 56px", padding: "0 16px", display: "flex", alignItems: "center", gap: 12, borderBottom: "1px solid var(--border-default)", background: "var(--surface-primary)", minWidth: 0 }}>
      <div style={{ fontFamily: "var(--font-sans)", fontSize: 18, lineHeight: 1, whiteSpace: "nowrap", overflow: "hidden", textOverflow: "ellipsis", minWidth: 0 }}>{title}</div>
      <div style={{ display: "flex", alignItems: "center", gap: 8, flex: "0 0 auto" }}>{children}</div>
      <div style={{ marginLeft: "auto", display: "flex", alignItems: "center", gap: 8, flex: "0 0 auto" }}>{right}</div>
    </div>
  );
}

function MonoLabel({ children, style }) {
  return <div style={{ fontFamily: "var(--font-mono)", fontSize: 12, lineHeight: 1.3, letterSpacing: "1.2px", textTransform: "uppercase", color: "var(--text-tertiary)", ...style }}>{children}</div>;
}

Object.assign(window, { Rail, PanelHead, MonoLabel });
