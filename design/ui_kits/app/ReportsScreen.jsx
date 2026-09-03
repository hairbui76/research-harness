// Reports: KPI row, stacked volume chart, topic table — the report palette in use.
const WEEK = [
  { d: "Mon", fin: 148, team: 62 }, { d: "Tue", fin: 172, team: 58 }, { d: "Wed", fin: 190, team: 71 },
  { d: "Thu", fin: 164, team: 49 }, { d: "Fri", fin: 205, team: 66 }, { d: "Sat", fin: 96, team: 12 }, { d: "Sun", fin: 88, team: 9 },
];
const TOPICS = [
  ["Billing & invoices", 412, "68%", "var(--color-report-green)"],
  ["Login & SSO", 268, "54%", "var(--color-report-blue)"],
  ["Shipping status", 221, "81%", "var(--color-report-lime)"],
  ["Refund policy", 174, "37%", "var(--color-report-orange)"],
  ["Bug reports", 131, "12%", "var(--color-report-pink)"],
];

function ReportsScreen() {
  const [range, setRange] = React.useState("7d");
  const max = Math.max(...WEEK.map((w) => w.fin + w.team));
  return (
    <div style={{ flex: 1, minWidth: 0, height: "100vh", overflow: "auto", background: "var(--surface-page)" }}>
      <PanelHead title="Reports" right={<>
        <Tabs items={[{ value: "7d", label: "7 days" }, { value: "30d", label: "30 days" }, { value: "qtr", label: "Quarter" }]} value={range} onChange={setRange} />
        <Button size="sm" variant="outlined"><Icon name="download" size={14} /> Export</Button>
      </>} />
      <div style={{ padding: 24, display: "flex", flexDirection: "column", gap: 20 }}>
        <div style={{ display: "grid", gridTemplateColumns: "repeat(4, 1fr)", gap: 16 }}>
          {[["Conversations", "1,482", "+8.2%", "var(--color-report-blue)"], ["Resolved by Fin", "65%", "+4.1pt", "var(--color-report-green)"], ["Median first reply", "1.2s", "-0.3s", "var(--color-report-lime)"], ["CSAT", "4.8", "+0.1", "var(--color-report-pink)"]].map(([l, v, d, c]) => (
            <Card key={l} padding={20} tone="white">
              <MonoLabel>{l}</MonoLabel>
              <div style={{ display: "flex", alignItems: "flex-end", gap: 10, marginTop: 16 }}>
                <span style={{ fontFamily: "var(--font-sans)", fontSize: 40, lineHeight: 1, letterSpacing: "-1.2px" }}>{v}</span>
                <span style={{ fontFamily: "var(--font-mono)", fontSize: 12, letterSpacing: "0.6px", color: "var(--text-muted)", paddingBottom: 4 }}>{d}</span>
              </div>
              <div style={{ height: 4, borderRadius: 2, background: c, marginTop: 16 }} />
            </Card>
          ))}
        </div>

        <Card padding={24} tone="white">
          <div style={{ display: "flex", alignItems: "center", justifyContent: "space-between" }}>
            <MonoLabel>Volume by day</MonoLabel>
            <div style={{ display: "flex", gap: 16 }}>
              {[["Fin", "var(--color-fin)"], ["Team", "var(--color-off-black)"]].map(([l, c]) => (
                <div key={l} style={{ display: "flex", alignItems: "center", gap: 6 }}>
                  <span style={{ width: 8, height: 8, background: c, borderRadius: 2 }} />
                  <span style={{ fontFamily: "var(--font-sans)", fontSize: 14, fontWeight: 300, color: "var(--text-secondary)" }}>{l}</span>
                </div>
              ))}
            </div>
          </div>
          <div style={{ display: "grid", gridTemplateColumns: "repeat(7, 1fr)", gap: 16, alignItems: "end", height: 200, marginTop: 24 }}>
            {WEEK.map((w) => (
              <div key={w.d} style={{ display: "flex", flexDirection: "column", justifyContent: "flex-end", gap: 2, height: "100%" }}>
                <div style={{ height: `${(w.team / max) * 100}%`, background: "var(--color-off-black)", borderRadius: "2px 2px 0 0" }} />
                <div style={{ height: `${(w.fin / max) * 100}%`, background: "var(--color-fin)", borderRadius: "0 0 2px 2px" }} />
                <MonoLabel style={{ textAlign: "center", marginTop: 8 }}>{w.d}</MonoLabel>
              </div>
            ))}
          </div>
        </Card>

        <Card padding={0} tone="white">
          <div style={{ padding: "20px 24px", borderBottom: "1px solid var(--border-default)", display: "flex", alignItems: "center", justifyContent: "space-between" }}>
            <MonoLabel>Top topics</MonoLabel>
            <Select size="sm" options={["Sorted by volume", "Sorted by resolution rate"]} />
          </div>
          <div style={{ display: "grid", gridTemplateColumns: "2fr 1fr 1fr 2fr", padding: "12px 24px", borderBottom: "1px solid var(--border-default)" }}>
            {["Topic", "Volume", "Fin resolved", ""].map((h) => <MonoLabel key={h}>{h}</MonoLabel>)}
          </div>
          {TOPICS.map(([t, v, r, c]) => (
            <div key={t} style={{ display: "grid", gridTemplateColumns: "2fr 1fr 1fr 2fr", padding: "16px 24px", borderBottom: "1px solid var(--border-default)", alignItems: "center" }}>
              <span style={{ fontFamily: "var(--font-sans)", fontSize: 16 }}>{t}</span>
              <span style={{ fontFamily: "var(--font-sans)", fontSize: 16, color: "var(--text-secondary)" }}>{v}</span>
              <span style={{ fontFamily: "var(--font-sans)", fontSize: 16, color: "var(--text-secondary)" }}>{r}</span>
              <div style={{ height: 6, background: "var(--surface-card)", borderRadius: 3, border: "1px solid var(--border-default)" }}>
                <div style={{ width: r, height: "100%", background: c, borderRadius: 3 }} />
              </div>
            </div>
          ))}
        </Card>
      </div>
    </div>
  );
}

Object.assign(window, { ReportsScreen });
