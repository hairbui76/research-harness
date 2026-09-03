// Marketing homepage: hero, trust strip, metric band, feature grid, editorial quote.
const HOME_FEATURES = [
  { icon: "sparkles", title: "Fin answers instantly", body: "An AI agent trained on your help center, macros and past conversations — live in a day, not a quarter.", accent: true },
  { icon: "inbox", title: "One desk for the rest", body: "Email, chat, phone and social land in a single inbox with the context your team already trusts." },
  { icon: "bar-chart-3", title: "Reporting you'll read", body: "Resolution rate, first reply, CSAT and cost per conversation — in one view, no spreadsheet." },
];
const HOME_STATS = [["65%", "resolved instantly"], ["1.2s", "median first reply"], ["45", "languages"], ["24/7", "coverage"]];

function HomeScreen({ onRoute }) {
  return (
    <main>
      <section style={{ maxWidth: 1200, margin: "0 auto", padding: "80px 40px 60px", display: "grid", gridTemplateColumns: "1.15fr 0.85fr", gap: 60, alignItems: "center" }}>
        <div>
          <Eyebrow>AI-first customer service</Eyebrow>
          <h1 style={{ margin: "24px 0 0", fontFamily: "var(--font-sans)", fontSize: 80, lineHeight: 1, letterSpacing: "-2.4px", fontWeight: 400 }}>Support that answers before you do.</h1>
          <p style={{ margin: "24px 0 0", fontFamily: "var(--font-sans)", fontSize: 20, lineHeight: 0.95, letterSpacing: "-0.2px", color: "var(--text-secondary)", maxWidth: 520, textWrap: "pretty" }}>Fin resolves the questions your team keeps repeating. Your people take the ones that matter.</p>
          <div style={{ display: "flex", gap: 12, marginTop: 32 }}>
            <Button size="lg">Start free trial</Button>
            <Button size="lg" variant="outlined" onClick={() => onRoute("product")}>See how Fin works</Button>
          </div>
          <div style={{ display: "flex", alignItems: "center", gap: 8, marginTop: 20 }}>
            <Icon name="check" size={14} color="var(--text-muted)" />
            <span style={{ fontFamily: "var(--font-sans)", fontSize: 14, fontWeight: 300, color: "var(--text-muted)" }}>14 days free · no card · cancel in one click</span>
          </div>
        </div>
        <div style={{ background: "var(--surface-primary)", border: "1px solid var(--border-default)", borderRadius: "var(--radius-card)", padding: 20 }}>
          <div style={{ display: "flex", alignItems: "center", justifyContent: "space-between" }}>
            <div style={{ display: "flex", alignItems: "center", gap: 8 }}>
              <span style={{ width: 8, height: 8, borderRadius: 999, background: "var(--color-fin)" }} />
              <span style={{ fontFamily: "var(--font-sans)", fontSize: 16 }}>Fin</span>
              <Badge tone="accent">AI</Badge>
            </div>
            <Eyebrow>Live</Eyebrow>
          </div>
          <div style={{ display: "flex", flexDirection: "column", gap: 12, marginTop: 20 }}>
            <div style={{ alignSelf: "flex-end", maxWidth: "78%", background: "var(--surface-inverse)", color: "var(--text-inverse)", borderRadius: "var(--radius-card)", padding: "12px 14px", fontFamily: "var(--font-sans)", fontSize: 14, lineHeight: 1.4 }}>My invoice charged twice this month — can you refund one?</div>
            <div style={{ alignSelf: "flex-start", maxWidth: "88%", background: "var(--surface-card)", border: "1px solid var(--border-default)", borderRadius: "var(--radius-card)", padding: "12px 14px", fontFamily: "var(--font-sans)", fontSize: 14, lineHeight: 1.4 }}>I found two charges on 4 Sept for $49. I've refunded the duplicate — it'll clear in 3–5 days. Here's the receipt.</div>
            <div style={{ alignSelf: "flex-start", display: "flex", alignItems: "center", gap: 8, paddingLeft: 2 }}>
              <Icon name="file-text" size={14} color="var(--text-muted)" />
              <span style={{ fontFamily: "var(--font-mono)", fontSize: 12, letterSpacing: "0.6px", color: "var(--text-muted)" }}>RECEIPT-4471.PDF</span>
            </div>
          </div>
          <div style={{ display: "flex", gap: 8, marginTop: 20, paddingTop: 16, borderTop: "1px solid var(--border-default)" }}>
            <Tag selected>Refunds</Tag><Tag>Billing</Tag><Tag>Resolved by Fin</Tag>
          </div>
        </div>
      </section>

      <LogoStrip />

      <section style={{ maxWidth: 1200, margin: "0 auto", padding: "60px 40px" }}>
        <div style={{ display: "grid", gridTemplateColumns: "repeat(4, 1fr)", gap: 24 }}>
          {HOME_STATS.map(([n, l]) => (
            <div key={l}>
              <div style={{ fontFamily: "var(--font-sans)", fontSize: 54, lineHeight: 1, letterSpacing: "-1.6px" }}>{n}</div>
              <Eyebrow style={{ marginTop: 12 }}>{l}</Eyebrow>
            </div>
          ))}
        </div>
      </section>

      <section style={{ maxWidth: 1200, margin: "0 auto", padding: "40px 40px 80px" }}>
        <h2 style={{ margin: 0, fontFamily: "var(--font-sans)", fontSize: 54, lineHeight: 1, letterSpacing: "-1.6px", fontWeight: 400, maxWidth: 720 }}>Everything a support team runs on, in one place.</h2>
        <div style={{ display: "grid", gridTemplateColumns: "repeat(3, 1fr)", gap: 20, marginTop: 40 }}>
          {HOME_FEATURES.map((f) => (
            <Card key={f.title} padding={24} interactive>
              <Icon name={f.icon} size={24} color={f.accent ? "var(--color-fin)" : "var(--text-primary)"} />
              <h3 style={{ margin: "60px 0 0", fontFamily: "var(--font-sans)", fontSize: 32, lineHeight: 1, letterSpacing: "-0.96px", fontWeight: 400 }}>{f.title}</h3>
              <p style={{ margin: "16px 0 0", fontFamily: "var(--font-sans)", fontSize: 16, lineHeight: 1.5, color: "var(--text-secondary)", textWrap: "pretty" }}>{f.body}</p>
              <div style={{ display: "flex", alignItems: "center", gap: 6, marginTop: 24, fontFamily: "var(--font-sans)", fontSize: 16 }}>
                Learn more <Icon name="arrow-right" size={16} />
              </div>
            </Card>
          ))}
        </div>
      </section>

      <section style={{ background: "var(--surface-primary)", borderTop: "1px solid var(--border-default)", borderBottom: "1px solid var(--border-default)" }}>
        <div style={{ maxWidth: 1200, margin: "0 auto", padding: "80px 40px", display: "grid", gridTemplateColumns: "1fr 1fr", gap: 80, alignItems: "center" }}>
          <blockquote style={{ margin: 0 }}>
            <p style={{ margin: 0, fontFamily: "var(--font-serif)", fontSize: 40, lineHeight: 1.1, letterSpacing: "-1.2px", fontWeight: 300, textWrap: "pretty" }}>“We cut first-response time from four hours to under two seconds, and nobody on the team works a weekend anymore.”</p>
            <footer style={{ display: "flex", alignItems: "center", gap: 12, marginTop: 32 }}>
              <div style={{ fontFamily: "var(--font-sans)", fontSize: 16 }}>Dana Okoye</div>
              <div style={{ width: 1, height: 16, background: "var(--border-default)" }} />
              <div style={{ fontFamily: "var(--font-sans)", fontSize: 16, color: "var(--text-muted)" }}>Head of Support, Northwind</div>
            </footer>
          </blockquote>
          <div style={{ display: "grid", gridTemplateColumns: "1fr 1fr", gap: 16 }}>
            {[["Resolution rate", "65%", "var(--color-report-green)"], ["Cost per conversation", "-42%", "var(--color-report-blue)"], ["CSAT", "4.8", "var(--color-report-lime)"], ["Backlog", "-71%", "var(--color-report-pink)"]].map(([l, v, c]) => (
              <div key={l} style={{ border: "1px solid var(--border-default)", borderRadius: "var(--radius-card)", padding: 20, background: "var(--surface-card)" }}>
                <Eyebrow>{l}</Eyebrow>
                <div style={{ fontFamily: "var(--font-sans)", fontSize: 40, lineHeight: 1, letterSpacing: "-1.2px", marginTop: 16 }}>{v}</div>
                <div style={{ height: 4, borderRadius: 2, background: c, marginTop: 16 }} />
              </div>
            ))}
          </div>
        </div>
      </section>

      <CtaBand />
    </main>
  );
}

Object.assign(window, { HomeScreen });
