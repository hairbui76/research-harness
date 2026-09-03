# UI kit — Helpdesk app

Click-through recreation of the product side of the system: dark icon rail, white working
surfaces on the warm-cream canvas, oat hairlines instead of shadows, mono uppercase labels
for every metadata row, Fin Orange only where the AI agent appears.

| File | Surface |
| --- | --- |
| `index.html` | Mount + session state. Starts on sign-in; the rail switches Inbox / Reports / Settings; the sign-out icon returns to login. |
| `AppChrome.jsx` | `Rail` (icon nav with unread pip + tooltips), `PanelHead`, `MonoLabel`. |
| `LoginScreen.jsx` | Split sign-in: form card (validates empty password) beside an inverse metric panel. |
| `InboxScreen.jsx` | Three panes — filtered conversation list, thread with Fin bubbles, composer with "Draft with Fin", customer details panel, close-conversation `Dialog`, send `Toast`. |
| `ReportsScreen.jsx` | KPI cards, stacked Fin-vs-team volume chart, topic table with report-palette bars. |
| `SettingsScreen.jsx` | Section nav plus Fin configuration: tone `Select`, confidence `Radio` set, behaviour `Switch`es, language `Checkbox` grid with `Tag` summary, reset `Dialog`. |

Interactions worth trying: pick a conversation, click **Draft with Fin**, send (⌘↵ works),
close the conversation, switch the Open / Waiting / Closed tabs, then visit Reports and
Settings from the rail.

All primitives come from `_ds_bundle.js` — nothing is re-implemented locally.

**Provenance:** no source repo, Figma file or screenshots were supplied; conversations,
customers and metrics are invented placeholders. Layout follows the written brief in
`readme.md`, not a recreation of any specific vendor's app.
