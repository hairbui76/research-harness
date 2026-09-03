// Editorial blog article: mono metadata, serif body, pull quote, subscribe band.
function ArticleScreen() {
  return (
    <main style={{ background: "var(--surface-primary)" }}>
      <article style={{ maxWidth: 760, margin: "0 auto", padding: "80px 40px 40px" }}>
        <div style={{ display: "flex", gap: 16, alignItems: "center" }}>
          <Eyebrow color="var(--color-fin)">AI in support</Eyebrow>
          <Eyebrow>8 min read · 2 Sept 2026</Eyebrow>
        </div>
        <h1 style={{ margin: "24px 0 0", fontFamily: "var(--font-sans)", fontSize: 54, lineHeight: 1, letterSpacing: "-1.6px", fontWeight: 400 }}>The deflection metric is lying to you</h1>
        <p style={{ margin: "24px 0 0", fontFamily: "var(--font-sans)", fontSize: 20, lineHeight: 0.95, letterSpacing: "-0.2px", color: "var(--text-secondary)" }}>Every helpdesk vendor reports deflection. Almost none of them report whether the customer got what they wanted.</p>
        <div style={{ display: "flex", alignItems: "center", gap: 12, margin: "32px 0", padding: "20px 0", borderTop: "1px solid var(--border-default)", borderBottom: "1px solid var(--border-default)" }}>
          <div style={{ width: 36, height: 36, borderRadius: 999, background: "var(--surface-subtle)", display: "flex", alignItems: "center", justifyContent: "center", fontFamily: "var(--font-sans)", fontSize: 14 }}>MR</div>
          <div>
            <div style={{ fontFamily: "var(--font-sans)", fontSize: 16 }}>Mira Reyes</div>
            <div style={{ fontFamily: "var(--font-sans)", fontSize: 14, fontWeight: 300, color: "var(--text-muted)" }}>Support Research, Warmline</div>
          </div>
          <div style={{ marginLeft: "auto", display: "flex", gap: 8 }}>
            <IconButton name="link" variant="outlined" size="sm" />
            <IconButton name="bookmark" variant="outlined" size="sm" />
          </div>
        </div>
        {[
          "A deflected conversation is one that never reached a human. That is all it means. It does not mean the question was answered, and it certainly does not mean the customer left satisfied — a customer who gives up is deflected too.",
          "We looked at 1.4 million conversations across teams running an AI agent in front of their inbox. When we split deflection into resolved and abandoned, a third of what teams counted as a win was a customer walking away.",
        ].map((p, i) => <p key={i} style={{ margin: "0 0 20px", fontFamily: "var(--font-serif)", fontSize: 20, fontWeight: 300, lineHeight: 1.5, letterSpacing: "-0.16px", textWrap: "pretty" }}>{p}</p>)}
        <blockquote style={{ margin: "40px 0", padding: "24px 0 24px 24px", borderLeft: "2px solid var(--color-fin)" }}>
          <p style={{ margin: 0, fontFamily: "var(--font-sans)", fontSize: 32, lineHeight: 1, letterSpacing: "-0.96px" }}>Measure resolution, or measure nothing.</p>
        </blockquote>
        <h2 style={{ margin: "0 0 20px", fontFamily: "var(--font-sans)", fontSize: 32, lineHeight: 1, letterSpacing: "-0.96px", fontWeight: 400 }}>What to track instead</h2>
        <p style={{ margin: "0 0 20px", fontFamily: "var(--font-serif)", fontSize: 20, fontWeight: 300, lineHeight: 1.5, letterSpacing: "-0.16px" }}>Three numbers survive scrutiny: resolution rate, reopen rate within seven days, and CSAT on AI-only conversations. Track them together and the picture stops flattering you.</p>
        <div style={{ background: "var(--surface-card)", border: "1px solid var(--border-default)", borderRadius: "var(--radius-card)", padding: 20, margin: "32px 0" }}>
          <Eyebrow>Benchmark, Q3 2026</Eyebrow>
          <div style={{ display: "grid", gridTemplateColumns: "repeat(3, 1fr)", gap: 20, marginTop: 16 }}>
            {[["Resolution", "65%", "var(--color-report-green)"], ["Reopen", "6%", "var(--color-report-orange)"], ["CSAT (AI only)", "4.6", "var(--color-report-blue)"]].map(([l, v, c]) => (
              <div key={l}>
                <div style={{ fontFamily: "var(--font-sans)", fontSize: 32, lineHeight: 1, letterSpacing: "-0.96px" }}>{v}</div>
                <div style={{ height: 4, background: c, borderRadius: 2, margin: "12px 0" }} />
                <div style={{ fontFamily: "var(--font-sans)", fontSize: 14, fontWeight: 300, color: "var(--text-muted)" }}>{l}</div>
              </div>
            ))}
          </div>
        </div>
        <div style={{ display: "flex", gap: 8 }}><Tag>Reporting</Tag><Tag>Fin</Tag><Tag>Benchmarks</Tag></div>
      </article>

      <section style={{ borderTop: "1px solid var(--border-default)", background: "var(--surface-page)" }}>
        <div style={{ maxWidth: 760, margin: "0 auto", padding: "60px 40px", display: "flex", gap: 40, alignItems: "flex-end" }}>
          <div style={{ flex: 1 }}>
            <h3 style={{ margin: 0, fontFamily: "var(--font-sans)", fontSize: 40, lineHeight: 1, letterSpacing: "-1.2px", fontWeight: 400 }}>One good support read, monthly.</h3>
            <p style={{ margin: "16px 0 0", fontFamily: "var(--font-sans)", fontSize: 16, lineHeight: 1.5, color: "var(--text-secondary)" }}>No product news. No webinars.</p>
          </div>
          <div style={{ display: "flex", gap: 10, flex: "0 0 320px" }}>
            <Input placeholder="you@company.com" style={{ flex: 1 }} />
            <Button>Subscribe</Button>
          </div>
        </div>
      </section>
    </main>
  );
}

Object.assign(window, { ArticleScreen });
