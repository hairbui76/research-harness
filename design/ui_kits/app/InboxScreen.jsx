// Three-pane inbox: conversation list, thread with composer, customer details panel.
const CONVOS = [
  { id: 1, name: "Priya Raman", company: "Northwind", subject: "Charged twice for September", preview: "My invoice charged twice this month — can you refund one?", time: "2m", state: "open", ai: true, unread: true,
    msgs: [{ from: "them", t: "Hi — my invoice charged twice this month. Can you refund one?", at: "09:41" },
           { from: "fin", t: "I found two charges on 4 Sept for $49.00. I've refunded the duplicate — it should clear in 3–5 business days.", at: "09:41" },
           { from: "them", t: "Thanks. Can someone confirm the annual plan wasn't affected?", at: "09:44" }] },
  { id: 2, name: "Tomás Lund", company: "Parcel", subject: "SSO setup for 40 seats", preview: "We're rolling out SAML this week and need…", time: "18m", state: "open", unread: true,
    msgs: [{ from: "them", t: "We're rolling out SAML this week and need the metadata URL.", at: "09:12" }] },
  { id: 3, name: "Mei Fong", company: "Lumen", subject: "Fin gave a wrong refund window", preview: "It said 3 days, our policy is 10.", time: "1h", state: "waiting", ai: true,
    msgs: [{ from: "them", t: "Fin told a customer 3 days; our policy is 10 business days.", at: "08:20" }] },
  { id: 4, name: "Alex Whitfield", company: "Hatchway", subject: "Exporting conversation history", preview: "Is there a CSV export with tags included?", time: "3h", state: "open",
    msgs: [{ from: "them", t: "Is there a CSV export that includes tags?", at: "06:55" }] },
  { id: 5, name: "Sara Nowak", company: "Vela", subject: "Thanks for the quick fix", preview: "All sorted — appreciate it.", time: "Yesterday", state: "closed",
    msgs: [{ from: "them", t: "All sorted — appreciate it.", at: "17:02" }] },
];
const FILTERS = [{ value: "open", label: "Open", count: 12 }, { value: "waiting", label: "Waiting", count: 3 }, { value: "closed", label: "Closed" }];

function ConvoRow({ c, active, onClick }) {
  const [hover, setHover] = React.useState(false);
  return (
    <button onClick={onClick} onMouseEnter={() => setHover(true)} onMouseLeave={() => setHover(false)}
      style={{ display: "block", width: "100%", textAlign: "left", padding: "14px 16px", border: 0, borderBottom: "1px solid var(--border-default)", cursor: "pointer",
               background: active ? "var(--surface-primary)" : hover ? "var(--color-white)" : "transparent", borderLeft: active ? "2px solid var(--color-off-black)" : "2px solid transparent" }}>
      <div style={{ display: "flex", alignItems: "center", gap: 8 }}>
        <div style={{ width: 24, height: 24, borderRadius: 999, background: "var(--color-sand)", display: "flex", alignItems: "center", justifyContent: "center", fontFamily: "var(--font-sans)", fontSize: 11 }}>{c.name.split(" ").map((n) => n[0]).join("")}</div>
        <span style={{ fontFamily: "var(--font-sans)", fontSize: 16, lineHeight: 1 }}>{c.name}</span>
        {c.ai && <span style={{ width: 6, height: 6, borderRadius: 999, background: "var(--color-fin)" }} />}
        <span style={{ marginLeft: "auto", fontFamily: "var(--font-mono)", fontSize: 11, letterSpacing: "0.6px", color: "var(--text-tertiary)" }}>{c.time}</span>
      </div>
      <div style={{ fontFamily: "var(--font-sans)", fontSize: 14, marginTop: 8, fontWeight: c.unread ? 400 : 300 }}>{c.subject}</div>
      <div style={{ fontFamily: "var(--font-sans)", fontSize: 14, fontWeight: 300, color: "var(--text-muted)", marginTop: 4, overflow: "hidden", textOverflow: "ellipsis", whiteSpace: "nowrap" }}>{c.preview}</div>
    </button>
  );
}

function Bubble({ m }) {
  const mine = m.from === "me";
  const fin = m.from === "fin";
  return (
    <div style={{ display: "flex", flexDirection: "column", alignItems: mine ? "flex-end" : "flex-start", gap: 6 }}>
      {fin && <div style={{ display: "flex", alignItems: "center", gap: 6 }}><span style={{ width: 6, height: 6, borderRadius: 999, background: "var(--color-fin)" }} /><MonoLabel style={{ color: "var(--color-fin)" }}>Fin · AI agent</MonoLabel></div>}
      <div style={{ maxWidth: "72%", padding: "12px 14px", borderRadius: "var(--radius-card)", fontFamily: "var(--font-sans)", fontSize: 16, lineHeight: 1.5,
                    background: mine ? "var(--surface-inverse)" : "var(--surface-card)", color: mine ? "var(--text-inverse)" : "var(--text-primary)",
                    border: mine ? "1px solid var(--color-off-black)" : "1px solid var(--border-default)" }}>{m.t}</div>
      <MonoLabel style={{ fontSize: 11 }}>{m.at}</MonoLabel>
    </div>
  );
}

function DetailsPanel({ c, onClose }) {
  return (
    <aside style={{ width: 296, flex: "0 0 296px", borderLeft: "1px solid var(--border-default)", background: "var(--surface-page)", overflow: "auto" }}>
      <PanelHead title="Details" right={<IconButton name="panel-right-close" size="sm" onClick={onClose} label="Hide details" />} />
      <div style={{ padding: 16, display: "flex", flexDirection: "column", gap: 20 }}>
        <div style={{ display: "flex", alignItems: "center", gap: 12 }}>
          <div style={{ width: 40, height: 40, borderRadius: 999, background: "var(--color-sand)", display: "flex", alignItems: "center", justifyContent: "center", fontFamily: "var(--font-sans)", fontSize: 14 }}>{c.name.split(" ").map((n) => n[0]).join("")}</div>
          <div>
            <div style={{ fontFamily: "var(--font-sans)", fontSize: 16 }}>{c.name}</div>
            <div style={{ fontFamily: "var(--font-sans)", fontSize: 14, fontWeight: 300, color: "var(--text-muted)" }}>{c.company}</div>
          </div>
        </div>
        <div>
          <MonoLabel>Customer</MonoLabel>
          <div style={{ marginTop: 12, display: "flex", flexDirection: "column", gap: 10 }}>
            {[["Plan", "Growth · yearly"], ["Seats", "42"], ["MRR", "$2,898"], ["Since", "Mar 2024"], ["Region", "EU (Frankfurt)"]].map(([k, v]) => (
              <div key={k} style={{ display: "flex", justifyContent: "space-between", gap: 12, fontFamily: "var(--font-sans)", fontSize: 14 }}>
                <span style={{ color: "var(--text-muted)", fontWeight: 300 }}>{k}</span><span>{v}</span>
              </div>
            ))}
          </div>
        </div>
        <div>
          <MonoLabel>Tags</MonoLabel>
          <div style={{ display: "flex", flexWrap: "wrap", gap: 8, marginTop: 12 }}><Tag selected>VIP</Tag><Tag onRemove={() => {}}>Billing</Tag><Tag onRemove={() => {}}>Refund</Tag></div>
        </div>
        <div>
          <MonoLabel>Recent conversations</MonoLabel>
          <div style={{ marginTop: 12, display: "flex", flexDirection: "column", gap: 8 }}>
            {[["Invoice PDF missing", "Resolved by Fin"], ["Add seats mid-term", "Resolved by Dana"], ["Data residency question", "Resolved by Fin"]].map(([t, s]) => (
              <div key={t} style={{ padding: 12, background: "var(--surface-primary)", border: "1px solid var(--border-default)", borderRadius: "var(--radius-card)" }}>
                <div style={{ fontFamily: "var(--font-sans)", fontSize: 14 }}>{t}</div>
                <div style={{ fontFamily: "var(--font-sans)", fontSize: 14, fontWeight: 300, color: "var(--text-muted)", marginTop: 4 }}>{s}</div>
              </div>
            ))}
          </div>
        </div>
      </div>
    </aside>
  );
}

function InboxScreen() {
  const [filter, setFilter] = React.useState("open");
  const [activeId, setActiveId] = React.useState(1);
  const [threads, setThreads] = React.useState(() => Object.fromEntries(CONVOS.map((c) => [c.id, c.msgs])));
  const [draft, setDraft] = React.useState("");
  const [details, setDetails] = React.useState(true);
  const [toast, setToast] = React.useState(null);
  const [closing, setClosing] = React.useState(false);

  const list = CONVOS.filter((c) => c.state === filter);
  const active = CONVOS.find((c) => c.id === activeId) || list[0] || CONVOS[0];
  const msgs = threads[active.id] || [];

  const threadRef = React.useRef(null);
  React.useEffect(() => { const el = threadRef.current; if (el) el.scrollTop = el.scrollHeight; }, [threads, activeId]);

  const send = () => {
    if (!draft.trim()) return;
    setThreads((t) => ({ ...t, [active.id]: [...(t[active.id] || []), { from: "me", t: draft.trim(), at: "09:47" }] }));
    setDraft("");
    setToast({ tone: "success", title: "Reply sent", description: active.name + " will be notified by email." });
  };
  const finDraft = () => setDraft("Confirmed — your annual plan is untouched. Only the duplicate $49.00 charge from 4 Sept was refunded, and it will clear in 3–5 business days.");

  return (
    <div style={{ display: "flex", flex: 1, minWidth: 0, height: "100vh", overflow: "hidden" }}>
      <section style={{ width: 320, flex: "0 0 320px", borderRight: "1px solid var(--border-default)", display: "flex", flexDirection: "column", background: "var(--surface-page)" }}>
        <PanelHead title="Inbox" right={<><IconButton name="filter" size="sm" label="Filter" /><IconButton name="pen-line" size="sm" variant="solid" label="New conversation" /></>} />
        <div style={{ padding: "12px 16px", borderBottom: "1px solid var(--border-default)", background: "var(--surface-primary)" }}>
          <Input size="sm" iconLeft="search" placeholder="Search conversations" />
        </div>
        <div style={{ padding: "0 16px", background: "var(--surface-primary)", borderBottom: "1px solid var(--border-default)" }}>
          <Tabs items={FILTERS} value={filter} onChange={(v) => { setFilter(v); const first = CONVOS.find((c) => c.state === v); if (first) setActiveId(first.id); }} />
        </div>
        <div style={{ overflow: "auto", flex: 1 }}>
          {list.map((c) => <ConvoRow key={c.id} c={c} active={c.id === active.id} onClick={() => setActiveId(c.id)} />)}
          {!list.length && <div style={{ padding: 24, fontFamily: "var(--font-sans)", fontSize: 14, fontWeight: 300, color: "var(--text-muted)" }}>Nothing here. Nice.</div>}
        </div>
      </section>

      <section style={{ flex: 1, minWidth: 380, display: "flex", flexDirection: "column", background: "var(--surface-primary)" }}>
        <PanelHead title={active.subject}
          children={<><Badge tone={active.state === "closed" ? "neutral" : active.state === "waiting" ? "info" : "success"}>{active.state}</Badge>{active.ai && <Badge tone="accent">Fin handled</Badge>}</>}
          right={<>
            <Select size="sm" options={["Assign to Dana", "Assign to Mira", "Assign to Fin"]} />
            <Button size="sm" variant="outlined" onClick={() => setClosing(true)}>Close</Button>
            {!details && <IconButton name="panel-right-open" size="sm" onClick={() => setDetails(true)} label="Show details" />}
          </>} />
        <div ref={threadRef} style={{ flex: 1, overflow: "auto", padding: 24, display: "flex", flexDirection: "column", gap: 20, background: "var(--surface-primary)" }}>
          <div style={{ display: "flex", alignItems: "center", gap: 12 }}>
            <div style={{ flex: 1, height: 1, background: "var(--border-default)" }} />
            <MonoLabel>Today</MonoLabel>
            <div style={{ flex: 1, height: 1, background: "var(--border-default)" }} />
          </div>
          {msgs.map((m, i) => <Bubble key={i} m={m} />)}
        </div>
        <div style={{ borderTop: "1px solid var(--border-default)", padding: 16, background: "var(--surface-page)" }}>
          <div style={{ border: "1px solid var(--border-default)", borderRadius: "var(--radius-card)", background: "var(--surface-primary)" }}>
            <textarea value={draft} onChange={(e) => setDraft(e.target.value)} placeholder="Write a reply…  ⌘↵ to send"
              style={{ width: "100%", minHeight: 84, resize: "none", border: 0, outline: "none", background: "transparent", padding: 14, boxSizing: "border-box", fontFamily: "var(--font-sans)", fontSize: 16, lineHeight: 1.5, color: "var(--text-primary)" }}
              onKeyDown={(e) => { if (e.key === "Enter" && (e.metaKey || e.ctrlKey)) send(); }} />
            <div style={{ display: "flex", alignItems: "center", gap: 8, padding: "10px 12px", borderTop: "1px solid var(--border-default)", minWidth: 0, flexWrap: "wrap" }}>
              <IconButton name="paperclip" size="sm" label="Attach" />
              <IconButton name="smile" size="sm" label="Emoji" />
              <IconButton name="zap" size="sm" label="Macros" />
              <Button size="sm" variant="accent" onClick={finDraft}><Icon name="sparkles" size={14} /> Draft with Fin</Button>
              <div style={{ marginLeft: "auto", display: "flex", alignItems: "center", gap: 8 }}>
                <MonoLabel>Public reply</MonoLabel>
                <Button size="sm" onClick={send}>Send</Button>
              </div>
            </div>
          </div>
        </div>
      </section>

      {details && <DetailsPanel c={active} onClose={() => setDetails(false)} />}

      <Dialog open={closing} title="Close this conversation?" description="Fin will keep learning from it. The customer can reopen by replying."
        onClose={() => setClosing(false)}
        footer={<><Button variant="ghost" onClick={() => setClosing(false)}>Cancel</Button><Button onClick={() => { setClosing(false); setToast({ tone: "neutral", title: "Conversation closed", description: active.subject }); }}>Close conversation</Button></>} />

      {toast && <div style={{ position: "fixed", bottom: 20, left: 84, zIndex: 60 }}><Toast tone={toast.tone} title={toast.title} description={toast.description} onDismiss={() => setToast(null)} /></div>}
    </div>
  );
}

Object.assign(window, { InboxScreen });
