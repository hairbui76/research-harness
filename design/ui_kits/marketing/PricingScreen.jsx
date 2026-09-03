// Pricing page: term switch, three plans, comparison rows, FAQ.
const PLANS = [
  { name: "Essential", price: [39, 29], blurb: "For small teams getting off email.", features: ["Shared inbox", "Help center", "2 seats included", "Email + chat"], cta: "Start free trial", variant: "outlined" },
  { name: "Growth", price: [85, 69], blurb: "For teams running Fin in production.", features: ["Everything in Essential", "Fin AI agent", "SAML SSO", "Custom reporting", "Workflows"], cta: "Start free trial", variant: "primary", featured: true },
  { name: "Enterprise", price: null, blurb: "For regulated and high-volume support.", features: ["Everything in Growth", "Dedicated region", "Audit log + HIPAA", "Named CSM"], cta: "Talk to sales", variant: "warm" },
];
const ROWS = [["Conversations / month", "1,000", "Unlimited", "Unlimited"], ["Fin resolutions", "—", "Pay per resolution", "Committed volume"], ["Languages", "8", "45", "45"], ["Support SLA", "Business hours", "24/5", "24/7 + phone"]];

function PricingScreen() {
  const [yearly, setYearly] = React.useState(true);
  return (
    <main>
      <section style={{ maxWidth: 1200, margin: "0 auto", padding: "80px 40px 40px", textAlign: "center" }}>
        <Eyebrow style={{ display: "flex", justifyContent: "center" }}>Pricing</Eyebrow>
        <h1 style={{ margin: "24px auto 0", fontFamily: "var(--font-sans)", fontSize: 80, lineHeight: 1, letterSpacing: "-2.4px", fontWeight: 400, maxWidth: 800 }}>Pay per seat. Pay per resolution.</h1>
        <div style={{ display: "flex", alignItems: "center", justifyContent: "center", gap: 14, marginTop: 32 }}>
          <span style={{ fontFamily: "var(--font-sans)", fontSize: 16, color: yearly ? "var(--text-muted)" : "var(--text-primary)" }}>Monthly</span>
          <Switch checked={yearly} onChange={setYearly} />
          <span style={{ fontFamily: "var(--font-sans)", fontSize: 16, color: yearly ? "var(--text-primary)" : "var(--text-muted)" }}>Yearly</span>
          <Badge tone="success">Save 20%</Badge>
        </div>
      </section>

      <section style={{ maxWidth: 1200, margin: "0 auto", padding: "20px 40px 60px", display: "grid", gridTemplateColumns: "repeat(3, 1fr)", gap: 20, alignItems: "stretch" }}>
        {PLANS.map((p) => (
          <div key={p.name} style={{ display: "flex", flexDirection: "column", background: p.featured ? "var(--surface-primary)" : "var(--surface-card)", border: p.featured ? "1px solid var(--border-strong)" : "1px solid var(--border-default)", borderRadius: "var(--radius-card)", padding: 24 }}>
            <div style={{ display: "flex", alignItems: "center", justifyContent: "space-between" }}>
              <div style={{ fontFamily: "var(--font-sans)", fontSize: 24, lineHeight: 1, letterSpacing: "-0.48px" }}>{p.name}</div>
              {p.featured && <Badge tone="accent">Most popular</Badge>}
            </div>
            <div style={{ marginTop: 24, display: "flex", alignItems: "flex-end", gap: 6 }}>
              {p.price ? <>
                <span style={{ fontFamily: "var(--font-sans)", fontSize: 54, lineHeight: 1, letterSpacing: "-1.6px" }}>${p.price[yearly ? 1 : 0]}</span>
                <span style={{ fontFamily: "var(--font-sans)", fontSize: 14, fontWeight: 300, color: "var(--text-muted)", paddingBottom: 6 }}>/ seat / mo</span>
              </> : <span style={{ fontFamily: "var(--font-sans)", fontSize: 54, lineHeight: 1, letterSpacing: "-1.6px" }}>Custom</span>}
            </div>
            <p style={{ margin: "16px 0 0", fontFamily: "var(--font-sans)", fontSize: 16, lineHeight: 1.5, color: "var(--text-secondary)" }}>{p.blurb}</p>
            <div style={{ display: "flex", flexDirection: "column", gap: 12, margin: "24px 0", paddingTop: 24, borderTop: "1px solid var(--border-default)" }}>
              {p.features.map((f) => (
                <div key={f} style={{ display: "flex", alignItems: "center", gap: 10 }}>
                  <Icon name="check" size={16} color={p.featured ? "var(--color-fin)" : "var(--text-primary)"} />
                  <span style={{ fontFamily: "var(--font-sans)", fontSize: 16 }}>{f}</span>
                </div>
              ))}
            </div>
            <Button variant={p.variant} fullWidth style={{ marginTop: "auto" }}>{p.cta}</Button>
          </div>
        ))}
      </section>

      <section style={{ background: "var(--surface-primary)", borderTop: "1px solid var(--border-default)", borderBottom: "1px solid var(--border-default)" }}>
        <div style={{ maxWidth: 1200, margin: "0 auto", padding: "60px 40px" }}>
          <Eyebrow>Compare plans</Eyebrow>
          <div style={{ marginTop: 24 }}>
            <div style={{ display: "grid", gridTemplateColumns: "1.6fr 1fr 1fr 1fr", padding: "0 0 12px", borderBottom: "1px solid var(--border-strong)" }}>
              {["", "Essential", "Growth", "Enterprise"].map((h, i) => <Eyebrow key={i} color="var(--text-primary)">{h}</Eyebrow>)}
            </div>
            {ROWS.map((r) => (
              <div key={r[0]} style={{ display: "grid", gridTemplateColumns: "1.6fr 1fr 1fr 1fr", padding: "16px 0", borderBottom: "1px solid var(--border-default)", alignItems: "center" }}>
                {r.map((c, i) => <span key={i} style={{ fontFamily: "var(--font-sans)", fontSize: 16, color: i === 0 ? "var(--text-primary)" : "var(--text-secondary)" }}>{c}</span>)}
              </div>
            ))}
          </div>
        </div>
      </section>

      <section style={{ maxWidth: 1200, margin: "0 auto", padding: "80px 40px" }}>
        <div style={{ display: "grid", gridTemplateColumns: "0.8fr 1.2fr", gap: 60 }}>
          <h2 style={{ margin: 0, fontFamily: "var(--font-sans)", fontSize: 40, lineHeight: 1, letterSpacing: "-1.2px", fontWeight: 400 }}>Questions we get every week</h2>
          <div>
            {[["What counts as a resolution?", "A conversation Fin closes without a human reply. If a teammate steps in, you're not charged."], ["Can we start with the inbox only?", "Yes. Essential has no Fin usage, and you can switch it on later without migrating anything."], ["Do you charge for light agents?", "No. Viewers and collaborators are free on every plan."]].map(([q, a]) => (
              <div key={q} style={{ padding: "20px 0", borderBottom: "1px solid var(--border-default)" }}>
                <div style={{ display: "flex", justifyContent: "space-between", gap: 20 }}>
                  <div style={{ fontFamily: "var(--font-sans)", fontSize: 24, lineHeight: 1, letterSpacing: "-0.48px" }}>{q}</div>
                  <Icon name="plus" size={18} color="var(--text-muted)" />
                </div>
                <p style={{ margin: "14px 0 0", fontFamily: "var(--font-serif)", fontSize: 16, fontWeight: 300, lineHeight: 1.4, letterSpacing: "-0.16px", color: "var(--text-secondary)", maxWidth: 520 }}>{a}</p>
              </div>
            ))}
          </div>
        </div>
      </section>

      <CtaBand />
    </main>
  );
}

Object.assign(window, { PricingScreen });
