// Marketing site chrome: top nav, section helpers, footer, CTA band.
const NAV = ["Product", "Solutions", "Pricing", "Docs", "Blog"];

function Wordmark({ size = 22, color = "var(--text-primary)" }) {
  return <div style={{ fontFamily: "var(--font-sans)", fontSize: size, lineHeight: 1, letterSpacing: size * -0.03, color, whiteSpace: "nowrap" }}>Warmline</div>;
}

function Eyebrow({ children, color = "var(--text-muted)", style }) {
  return <div style={{ fontFamily: "var(--font-mono)", fontSize: 12, lineHeight: 1.3, letterSpacing: "1.2px", textTransform: "uppercase", color, ...style }}>{children}</div>;
}

function Nav({ route, onRoute }) {
  return (
    <header style={{ position: "sticky", top: 0, zIndex: 20, background: "var(--surface-primary)", borderBottom: "1px solid var(--border-default)" }}>
      <div style={{ maxWidth: 1200, margin: "0 auto", padding: "0 40px", height: 64, display: "flex", alignItems: "center", gap: 40 }}>
        <a href="#" onClick={(e) => { e.preventDefault(); onRoute("home"); }} style={{ textDecoration: "none" }}><Wordmark /></a>
        <nav style={{ display: "flex", alignItems: "center", gap: 24, flex: 1 }}>
          {NAV.map((n) => {
            const key = n.toLowerCase();
            const on = route === key || (key === "product" && route === "product");
            return (
              <a key={n} href="#" onClick={(e) => { e.preventDefault(); onRoute(key === "blog" ? "article" : key); }}
                 style={{ fontFamily: "var(--font-sans)", fontSize: 16, lineHeight: 1, color: on ? "var(--text-primary)" : "var(--text-secondary)", textDecoration: "none", display: "flex", alignItems: "center", gap: 6 }}>
                {n}{n === "Solutions" && <Icon name="chevron-down" size={14} color="var(--text-tertiary)" />}
              </a>
            );
          })}
        </nav>
        <div style={{ display: "flex", alignItems: "center", gap: 10 }}>
          <Button variant="ghost" size="sm">Sign in</Button>
          <Button size="sm">Start free trial</Button>
        </div>
      </div>
    </header>
  );
}

function LogoStrip() {
  return (
    <div style={{ borderTop: "1px solid var(--border-default)", borderBottom: "1px solid var(--border-default)", background: "var(--surface-primary)" }}>
      <div style={{ maxWidth: 1200, margin: "0 auto", padding: "24px 40px", display: "flex", alignItems: "center", gap: 40 }}>
        <Eyebrow style={{ flex: "0 0 auto" }}>Trusted by 25,000+ teams</Eyebrow>
        <div style={{ display: "flex", gap: 40, flex: 1, justifyContent: "flex-end", alignItems: "center" }}>
          {["Northwind", "Lumen", "Parcel", "Hatchway", "Vela", "Orbit"].map((c) => (
            <div key={c} style={{ fontFamily: "var(--font-sans)", fontSize: 20, letterSpacing: "-0.4px", color: "var(--color-black-50)" }}>{c}</div>
          ))}
        </div>
      </div>
    </div>
  );
}

function CtaBand() {
  return (
    <section style={{ background: "var(--surface-inverse)", color: "var(--text-inverse)" }}>
      <div style={{ maxWidth: 1200, margin: "0 auto", padding: "96px 40px", display: "flex", alignItems: "flex-end", justifyContent: "space-between", gap: 60 }}>
        <div style={{ maxWidth: 640 }}>
          <Eyebrow color="var(--color-sand)">Get started</Eyebrow>
          <h2 style={{ margin: "20px 0 0", fontFamily: "var(--font-sans)", fontSize: 54, lineHeight: 1, letterSpacing: "-1.6px", fontWeight: 400 }}>Turn support into your fastest team.</h2>
        </div>
        <div style={{ display: "flex", gap: 12, flex: "0 0 auto" }}>
          <Button variant="warm">Start free trial</Button>
          <Button variant="outlined" style={{ color: "var(--text-inverse)", borderColor: "var(--color-black-60)" }}>Book a demo</Button>
        </div>
      </div>
    </section>
  );
}

function Footer() {
  const cols = [
    ["Product", ["AI agent", "Inbox", "Help center", "Reports", "Integrations"]],
    ["Solutions", ["Support teams", "Startups", "E-commerce", "Financial services"]],
    ["Resources", ["Docs", "Changelog", "Community", "Status"]],
    ["Company", ["About", "Careers", "Security", "Contact"]],
  ];
  return (
    <footer style={{ background: "var(--surface-primary)", borderTop: "1px solid var(--border-default)" }}>
      <div style={{ maxWidth: 1200, margin: "0 auto", padding: "60px 40px 32px", display: "grid", gridTemplateColumns: "1.4fr repeat(4, 1fr)", gap: 40 }}>
        <div>
          <Wordmark size={24} />
          <p style={{ margin: "16px 0 0", fontFamily: "var(--font-sans)", fontSize: 14, fontWeight: 300, lineHeight: 1.4, color: "var(--text-muted)", maxWidth: 240 }}>The customer service platform with an AI agent at the front.</p>
        </div>
        {cols.map(([label, links]) => (
          <div key={label}>
            <Eyebrow>{label}</Eyebrow>
            <div style={{ display: "flex", flexDirection: "column", gap: 10, marginTop: 16 }}>
              {links.map((l) => <a key={l} href="#" onClick={(e) => e.preventDefault()} style={{ fontFamily: "var(--font-sans)", fontSize: 14, fontWeight: 300, color: "var(--text-secondary)", textDecoration: "none" }}>{l}</a>)}
            </div>
          </div>
        ))}
      </div>
      <div style={{ maxWidth: 1200, margin: "0 auto", padding: "20px 40px 40px", borderTop: "1px solid var(--border-default)", display: "flex", justifyContent: "space-between" }}>
        <Eyebrow>© 2026 Warmline</Eyebrow>
        <Eyebrow>Privacy · Terms · Cookies</Eyebrow>
      </div>
    </footer>
  );
}

Object.assign(window, { Wordmark, Eyebrow, Nav, LogoStrip, CtaBand, Footer });
