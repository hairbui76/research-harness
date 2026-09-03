// Sign-in screen: warm-cream canvas, single card, real form primitives.
function LoginScreen({ onSignIn }) {
  const [email, setEmail] = React.useState("dana@northwind.com");
  const [pw, setPw] = React.useState("");
  const [remember, setRemember] = React.useState(true);
  const [err, setErr] = React.useState("");
  const submit = (e) => {
    e.preventDefault();
    if (!pw) { setErr("Enter your password to continue."); return; }
    onSignIn();
  };
  return (
    <div style={{ minHeight: "100vh", background: "var(--surface-page)", display: "grid", gridTemplateColumns: "1fr 1fr" }}>
      <div style={{ display: "flex", alignItems: "center", justifyContent: "center", padding: 40 }}>
        <form onSubmit={submit} style={{ width: 380, background: "var(--surface-primary)", border: "1px solid var(--border-default)", borderRadius: "var(--radius-card)", padding: 32 }}>
          <div style={{ fontFamily: "var(--font-sans)", fontSize: 24, lineHeight: 1, letterSpacing: "-0.48px" }}>Warmline</div>
          <h1 style={{ margin: "24px 0 0", fontFamily: "var(--font-sans)", fontSize: 40, lineHeight: 1, letterSpacing: "-1.2px", fontWeight: 400 }}>Sign in</h1>
          <div style={{ display: "flex", flexDirection: "column", gap: 16, marginTop: 24 }}>
            <Input label="Work email" iconLeft="mail" value={email} onChange={(e) => setEmail(e.target.value)} />
            <Input label="Password" type="password" placeholder="••••••••" value={pw} error={err} onChange={(e) => { setPw(e.target.value); setErr(""); }} />
            <div style={{ display: "flex", alignItems: "center", justifyContent: "space-between" }}>
              <Checkbox label="Keep me signed in" checked={remember} onChange={setRemember} />
              <a href="#" onClick={(e) => e.preventDefault()} style={{ fontFamily: "var(--font-sans)", fontSize: 14, fontWeight: 300, color: "var(--text-secondary)" }}>Forgot?</a>
            </div>
            <Button type="submit" fullWidth size="lg">Sign in</Button>
            <Button variant="outlined" fullWidth><Icon name="key-round" size={16} /> Continue with SSO</Button>
          </div>
          <div style={{ marginTop: 24, paddingTop: 20, borderTop: "1px solid var(--border-default)", fontFamily: "var(--font-sans)", fontSize: 14, fontWeight: 300, color: "var(--text-muted)" }}>
            New here? <a href="#" onClick={(e) => e.preventDefault()}>Start a free trial</a>
          </div>
        </form>
      </div>
      <div style={{ background: "var(--surface-inverse)", color: "var(--text-inverse)", padding: 60, display: "flex", flexDirection: "column", justifyContent: "center" }}>
        <MonoLabel style={{ color: "var(--color-sand)" }}>This week in your workspace</MonoLabel>
        <div style={{ display: "grid", gridTemplateColumns: "1fr 1fr", gap: 24, marginTop: 32 }}>
          {[["1,482", "conversations", "var(--color-report-blue)"], ["65%", "resolved by Fin", "var(--color-report-green)"], ["1.2s", "median first reply", "var(--color-report-lime)"], ["4.8", "CSAT", "var(--color-report-pink)"]].map(([v, l, c]) => (
            <div key={l}>
              <div style={{ fontFamily: "var(--font-sans)", fontSize: 54, lineHeight: 1, letterSpacing: "-1.6px" }}>{v}</div>
              <div style={{ height: 4, background: c, borderRadius: 2, margin: "12px 0" }} />
              <MonoLabel style={{ color: "var(--color-black-50)" }}>{l}</MonoLabel>
            </div>
          ))}
        </div>
      </div>
    </div>
  );
}

Object.assign(window, { LoginScreen });
