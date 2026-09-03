// Settings: section nav, Fin configuration form, danger zone dialog.
function SettingsScreen() {
  const [section, setSection] = React.useState("fin");
  const [tone, setTone] = React.useState("Warm and brief");
  const [handover, setHandover] = React.useState(true);
  const [actions, setActions] = React.useState(true);
  const [langs, setLangs] = React.useState(["English", "German"]);
  const [confidence, setConfidence] = React.useState("balanced");
  const [saved, setSaved] = React.useState(false);
  const [reset, setReset] = React.useState(false);
  const NAV = [["fin", "Fin AI agent"], ["inbox", "Inbox"], ["team", "Teammates"], ["channels", "Channels"], ["security", "Security"]];

  return (
    <div style={{ flex: 1, minWidth: 0, height: "100vh", overflow: "auto", background: "var(--surface-page)" }}>
      <PanelHead title="Settings" right={<><Button size="sm" variant="ghost" onClick={() => setReset(true)}>Reset defaults</Button><Button size="sm" onClick={() => setSaved(true)}>Save changes</Button></>} />
      <div style={{ display: "grid", gridTemplateColumns: "232px 1fr", alignItems: "start" }}>
        <nav style={{ padding: 16, borderRight: "1px solid var(--border-default)", display: "flex", flexDirection: "column", gap: 4, position: "sticky", top: 0 }}>
          {NAV.map(([id, label]) => (
            <button key={id} onClick={() => setSection(id)}
              style={{ textAlign: "left", padding: "10px 12px", borderRadius: "var(--radius-nav)", border: 0, cursor: "pointer", fontFamily: "var(--font-sans)", fontSize: 16,
                       background: section === id ? "var(--surface-inverse)" : "transparent", color: section === id ? "var(--text-inverse)" : "var(--text-secondary)" }}>{label}</button>
          ))}
        </nav>
        <div style={{ padding: 24, maxWidth: 720, display: "flex", flexDirection: "column", gap: 20 }}>
          <div>
            <h1 style={{ margin: 0, fontFamily: "var(--font-sans)", fontSize: 40, lineHeight: 1, letterSpacing: "-1.2px", fontWeight: 400 }}>Fin AI agent</h1>
            <p style={{ margin: "16px 0 0", fontFamily: "var(--font-sans)", fontSize: 16, lineHeight: 1.5, color: "var(--text-secondary)" }}>Controls how Fin answers before a teammate sees the conversation.</p>
          </div>

          <Card padding={24} tone="white">
            <MonoLabel>Voice</MonoLabel>
            <div style={{ display: "grid", gridTemplateColumns: "1fr 1fr", gap: 16, marginTop: 16 }}>
              <Select label="Answer tone" options={["Warm and brief", "Neutral and precise", "Formal"]} value={tone} onChange={(e) => setTone(e.target.value)} />
              <Input label="Signature" defaultValue="— Fin, Warmline Support" />
            </div>
            <div style={{ marginTop: 16 }}>
              <Input label="Escalation message" hint="Sent when Fin hands over to a teammate." defaultValue="Let me bring in a teammate who can help with this." />
            </div>
          </Card>

          <Card padding={24} tone="white">
            <MonoLabel>Confidence threshold</MonoLabel>
            <div style={{ display: "flex", flexDirection: "column", gap: 12, marginTop: 16 }}>
              {[["cautious", "Cautious — answer only with a cited source"], ["balanced", "Balanced — answer when confident, hand over otherwise"], ["assertive", "Assertive — attempt every conversation"]].map(([v, l]) => (
                <Radio key={v} name="confidence" value={v} label={l} checked={confidence === v} onChange={() => setConfidence(v)} />
              ))}
            </div>
          </Card>

          <Card padding={24} tone="white">
            <MonoLabel>Behaviour</MonoLabel>
            <div style={{ display: "flex", flexDirection: "column", gap: 16, marginTop: 16 }}>
              <Switch label="Hand over to a teammate on low confidence" checked={handover} onChange={setHandover} />
              <Switch label="Allow Fin to take actions (refunds, plan changes)" checked={actions} onChange={setActions} />
              <Switch label="Answer outside business hours only" checked={false} onChange={() => {}} disabled />
            </div>
          </Card>

          <Card padding={24} tone="white">
            <MonoLabel>Languages</MonoLabel>
            <div style={{ display: "grid", gridTemplateColumns: "1fr 1fr", gap: 12, marginTop: 16 }}>
              {["English", "German", "French", "Japanese", "Portuguese", "Korean"].map((l) => (
                <Checkbox key={l} label={l} checked={langs.includes(l)} onChange={(on) => setLangs((s) => (on ? [...s, l] : s.filter((x) => x !== l)))} />
              ))}
            </div>
            <div style={{ display: "flex", gap: 8, marginTop: 20, paddingTop: 20, borderTop: "1px solid var(--border-default)" }}>
              {langs.map((l) => <Tag key={l} selected onRemove={() => setLangs((s) => s.filter((x) => x !== l))}>{l}</Tag>)}
            </div>
          </Card>

          <div style={{ display: "flex", justifyContent: "flex-end", gap: 12, paddingBottom: 40 }}>
            <Button variant="outlined">Preview answers</Button>
            <Button onClick={() => setSaved(true)}>Save changes</Button>
          </div>
        </div>
      </div>

      <Dialog open={reset} title="Reset Fin to defaults?" description="Tone, threshold and language settings return to the Warmline defaults. Content sources are untouched."
        onClose={() => setReset(false)}
        footer={<><Button variant="ghost" onClick={() => setReset(false)}>Cancel</Button><Button onClick={() => { setReset(false); setSaved(true); }}>Reset</Button></>} />
      {saved && <div style={{ position: "fixed", bottom: 20, left: 84, zIndex: 60 }}><Toast tone="success" title="Settings saved" description="Fin is using the new configuration." onDismiss={() => setSaved(false)} /></div>}
    </div>
  );
}

Object.assign(window, { SettingsScreen });
