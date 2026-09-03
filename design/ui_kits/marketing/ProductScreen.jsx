// Product page for the AI agent: split hero, capability list, source table.
const CAPABILITIES = [
  ["01", "Reads your content", "Point Fin at your help center, PDFs and past tickets. It cites what it used in every answer."],
  ["02", "Takes real actions", "Issue refunds, change a plan, resend a receipt — through the same APIs your team uses."],
  ["03", "Knows when to stop", "Low confidence, angry customer, VIP account: Fin hands over with a full summary attached."],
  ["04", "Improves weekly", "Every unresolved conversation becomes a content gap you can fix in one click."],
];

function ProductScreen({ onRoute }) {
  const [tab, setTab] = React.useState("answers");
  return (
    <main>
      <section style={{ background: "var(--surface-primary)", borderBottom: "1px solid var(--border-default)" }}>
        <div style={{ maxWidth: 1200, margin: "0 auto", padding: "80px 40px", display: "grid", gridTemplateColumns: "1fr 1fr", gap: 60, alignItems: "center" }}>
          <div>
            <div style={{ display: "flex", alignItems: "center", gap: 10 }}>
              <span style={{ width: 10, height: 10, borderRadius: 999, background: "var(--color-fin)" }} />
              <Eyebrow color="var(--color-fin)">Fin · AI agent</Eyebrow>
            </div>
            <h1 style={{ margin: "24px 0 0", fontFamily: "var(--font-sans)", fontSize: 80, lineHeight: 1, letterSpacing: "-2.4px", fontWeight: 400 }}>The agent that resolves, not deflects.</h1>
            <p style={{ margin: "24px 0 0", fontFamily: "var(--font-sans)", fontSize: 20, lineHeight: 0.95, letterSpacing: "-0.2px", color: "var(--text-secondary)", maxWidth: 480 }}>Answers grounded in your own content, with actions your customers can feel.</p>
            <div style={{ display: "flex", gap: 12, marginTop: 32 }}>
              <Button variant="accent" size="lg"><Icon name="sparkles" size={16} color="currentColor" /> Try Fin free</Button>
              <Button variant="outlined" size="lg" onClick={() => onRoute("pricing")}>See pricing</Button>
            </div>
          </div>
          <div style={{ border: "1px solid var(--border-default)", borderRadius: "var(--radius-card)", background: "var(--surface-card)", padding: 20 }}>
            <Tabs items={[{ value: "answers", label: "Answers" }, { value: "actions", label: "Actions" }, { value: "handover", label: "Handover" }]} value={tab} onChange={setTab} />
            <div style={{ marginTop: 20, display: "flex", flexDirection: "column", gap: 12, minHeight: 236 }}>
              {tab === "answers" && <>
                <div style={{ background: "var(--surface-primary)", border: "1px solid var(--border-default)", borderRadius: "var(--radius-card)", padding: 16, fontFamily: "var(--font-sans)", fontSize: 14, lineHeight: 1.4 }}>Do you support SSO on the Growth plan?</div>
                <div style={{ background: "var(--surface-primary)", border: "1px solid var(--border-default)", borderRadius: "var(--radius-card)", padding: 16 }}>
                  <p style={{ margin: 0, fontFamily: "var(--font-sans)", fontSize: 14, lineHeight: 1.4 }}>SAML SSO is included on Growth and above. You can enable it in Settings → Security; the setup takes about ten minutes.</p>
                  <div style={{ display: "flex", alignItems: "center", gap: 8, marginTop: 14, paddingTop: 14, borderTop: "1px solid var(--border-default)" }}>
                    <Icon name="book-open" size={14} color="var(--color-fin)" />
                    <span style={{ fontFamily: "var(--font-mono)", fontSize: 12, letterSpacing: "0.6px", textTransform: "uppercase", color: "var(--text-muted)" }}>Source: security/sso-setup</span>
                  </div>
                </div>
              </>}
              {tab === "actions" && <>
                {[["credit-card", "Refund issued", "$49.00 · card ending 4242"], ["user-cog", "Plan changed", "Starter → Growth, prorated"], ["mail", "Receipt resent", "dana@northwind.com"]].map(([ic, t, s]) => (
                  <div key={t} style={{ display: "flex", alignItems: "center", gap: 14, background: "var(--surface-primary)", border: "1px solid var(--border-default)", borderRadius: "var(--radius-card)", padding: 16 }}>
                    <Icon name={ic} size={20} color="var(--text-primary)" />
                    <div>
                      <div style={{ fontFamily: "var(--font-sans)", fontSize: 16 }}>{t}</div>
                      <div style={{ fontFamily: "var(--font-sans)", fontSize: 14, fontWeight: 300, color: "var(--text-muted)" }}>{s}</div>
                    </div>
                    <Badge tone="success" style={{ marginLeft: "auto" }}>Done</Badge>
                  </div>
                ))}
              </>}
              {tab === "handover" && <div style={{ background: "var(--surface-primary)", border: "1px solid var(--border-default)", borderRadius: "var(--radius-card)", padding: 16 }}>
                <Eyebrow>Handover summary</Eyebrow>
                <p style={{ margin: "14px 0 0", fontFamily: "var(--font-sans)", fontSize: 14, lineHeight: 1.4 }}>Customer was charged twice and is on a VIP account. Fin verified both charges, refunded one, and escalated because the customer asked for a call. Sentiment: frustrated.</p>
                <div style={{ display: "flex", gap: 8, marginTop: 16 }}><Tag selected>VIP</Tag><Tag>Billing</Tag><Tag>Callback requested</Tag></div>
              </div>}
            </div>
          </div>
        </div>
      </section>

      <section style={{ maxWidth: 1200, margin: "0 auto", padding: "80px 40px" }}>
        <Eyebrow>How it works</Eyebrow>
        <div style={{ display: "grid", gridTemplateColumns: "repeat(2, 1fr)", gap: 0, marginTop: 32, borderTop: "1px solid var(--border-default)" }}>
          {CAPABILITIES.map(([n, t, b]) => (
            <div key={n} style={{ display: "grid", gridTemplateColumns: "56px 1fr", gap: 20, padding: "32px 40px 32px 0", borderBottom: "1px solid var(--border-default)" }}>
              <Eyebrow style={{ paddingTop: 6 }}>{n}</Eyebrow>
              <div>
                <h3 style={{ margin: 0, fontFamily: "var(--font-sans)", fontSize: 32, lineHeight: 1, letterSpacing: "-0.96px", fontWeight: 400 }}>{t}</h3>
                <p style={{ margin: "16px 0 0", fontFamily: "var(--font-sans)", fontSize: 16, lineHeight: 1.5, color: "var(--text-secondary)", maxWidth: 420, textWrap: "pretty" }}>{b}</p>
              </div>
            </div>
          ))}
        </div>
      </section>

      <CtaBand />
    </main>
  );
}

Object.assign(window, { ProductScreen });
