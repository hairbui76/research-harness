# The Research Harness Design System

`design/` is `@research-harness/design`, a package in the pnpm workspace beside `web/` and
`vscode/`. It holds the semantic tokens, the dark and light themes, and the accessible
React primitives that every research surface composes, so that a button, a status chip or a
focus ring is defined once and looks the same in conversation, in a corpus table and in a
manuscript pane (PRODUCT §26; ROADMAP *Cross-cutting Foundation — Research Harness Design
System*; the design specification is
`docs/superpowers/specs/2026-09-03-research-harness-design-system-design.md`).

The package is presentation and nothing else. It contains no daemon client, no `fetch`, no
research rule and no state machine over accepted objects. Components receive typed view
models and callbacks; the Web client keeps the capability calls. That boundary is the same
one `docs/architecture/conventions.md` draws for `capabilities/` on the Python side: the
frontend layer that draws a decision is not the layer that is allowed to make it.

```text
tokens and themes
        v
presentation primitives
        v
research / conversation / manuscript / workspace components
        v
Web application screens
```

Dependencies only ever point down that list. A primitive does not import a research
component, and no design component imports the Web client's API layer.

## How the Web consumes it

`web/package.json` already depends on `@research-harness/design: workspace:*`, so the
package resolves through the workspace link and Vite compiles its TypeScript source
directly — there is no build step between changing a token and seeing it in `pnpm dev`.

Two imports set the client up:

```tsx
// web/src/main.tsx
import '@research-harness/design/styles.css';
```

```tsx
// anywhere in web/src
import { Button, Badge, Card, Input } from '@research-harness/design';
```

`styles.css` is the single stylesheet: it imports the palette, the token layer, both
themes, the document base, and every primitive's CSS, in that order. Linking anything else
from the package is unnecessary; `@research-harness/design/tokens/*` and `/themes/*` are
exported for tooling, not for a second `<link>`.

`pnpm --filter @research-harness/design build` emits `design/dist` with `.js`, `.d.ts` and
every `.css` at the same relative path, for a consumer that wants the compiled artefact
rather than the source.

## Theme and density are attributes

Dark is the default and requires no attribute at all: the theme's values are declared on a
bare `:root`, so a page renders correctly before any preference has been read from
`localStorage`. Light is opt-in.

```html
<html data-theme="light" data-density="compact">
```

Both attributes are also honoured on any element, so a surface can differ from the page:

```tsx
<article data-theme="light">…a manuscript pane in an otherwise dark application…</article>
<div data-density="compact">…a dense review queue inside a comfortable page…</div>
```

`color-scheme` is set per theme, so native scrollbars and form controls follow. The theme
preference is a local UI preference: it is stored on the machine and has no effect on
canonical state, on `.research/`, or on anything a model is sent.

`comfortable` (36px rows) is the default density and suits conversation and manuscript
reading; `compact` (28px rows) suits corpus tables, graph results and review queues.
Components read `--rh-density-row`, `--rh-density-gap`, `--rh-density-pad` and
`--rh-density-font-scale` rather than branching on the attribute themselves.

`prefers-reduced-motion: reduce` is handled once, in the token layer: durations collapse to
a single frame and the hover/press scales become `1`. A component that transitions using
`var(--rh-duration-fast)` is therefore already compliant.

## The token naming contract

Colour is addressed by meaning. `--rh-surface-pane` is "the working pane", not "warm grey";
what warm grey it resolves to is the theme's business.

| Group | Names | What it is for |
| --- | --- | --- |
| Surfaces | `--rh-surface-{canvas,pane,raised,paper,inverse,subtle,selected,scrim}` | the application background, working panes, cards/menus/popovers, the neutral reading surface, inverted bands, hover and selected tints, and the wash behind an overlay |
| Borders | `--rh-border-{subtle,default,strong}`, `--rh-border-on-paper` | separators through to the visible edge of a control |
| Text | `--rh-text-{primary,secondary,muted,inverse,link,on-accent}` | ink on the theme's surfaces |
| Paper ink | `--rh-text-on-paper{,-secondary,-muted}` | ink on `--rh-surface-paper` |
| Accent | `--rh-accent{,-hover,-subtle,-border,-fg,-text}` | the AI/action accent |
| Focus | `--rh-focus-ring{,-width,-offset}` | one focus treatment for the whole system |
| Status | `--rh-status-<accepted\|candidate\|qualified\|contested\|stale\|private>-<fg\|bg\|border>` | scientific authority |
| Feedback | `--rh-feedback-<success\|error\|warning\|info>-<fg\|bg\|border>` | transient application feedback |
| Type | `--rh-font-{sans,serif,mono}`, `--rh-type-<role>-{size,lh,ls,weight}` | roles `display h1 h2 h3 h4 lead ui body body-sm label mono` |
| Space, radius | `--rh-space-{1..16}` on a 4px base, `--rh-radius-{control,nav,card,pill}` | |
| Motion | `--rh-duration-{fast,base,slow}`, `--rh-ease-standard`, `--rh-scale-{hover,press}` | |
| Density | `--rh-density-{row,gap,pad,font-scale}` | |

Four rules give the names their meaning.

**Raw colour lives in `design/src/tokens/palette.css` and `design/src/themes/*.css`.**
Nowhere else, in either package. A literal in a component is a fork of the theme: it looks
right in dark and wrong in light, and it survives the palette change that everything around
it followed.

**The AI/action accent is not an emphasis colour.** It marks model activity, the primary
send/run action, active reference tracking and selected AI provenance. It never encodes
whether something is true. This is the one visual rule the product depends on most: a
researcher must be able to tell "a model did this" from "this is accepted" at a glance.

**Scientific status is never colour alone.** Each of the six states renders a glyph and a
label as well as its palette (`STATUS_META`), and the contrast gate additionally checks that
no status foreground has drifted close enough to the accent to be confused with it.

**`paper` is theme-independent.** A page of a source is near-white in dark mode as well as
light, so it carries its own ink tokens. Use `.rh-surface-paper` or `<Card surface="paper">`
rather than setting a background colour on its own.

## The gates

`pnpm --filter @research-harness/design lint` runs three things:

1. **eslint** with the TypeScript rules.
2. **`scripts/check-tokens.mjs`** — the raw-palette lint. It walks `design/src` and fails on
   any `#hex`, `rgb()`, `hsl()`, `oklab()`, `oklch()` or a `color-mix()` over literals
   outside `src/tokens` and `src/themes`. A genuine visualisation case annotates the line:

   ```css
   stroke: #65b5ff; /* raw-colour-ok: chart series 2, fixed across themes */
   ```

   The same rule is applied to `web/src`, and since the migration finished it **fails**
   there too: every cockpit route is on the package, so a literal in the Web client forks
   the theme exactly as one here would. The script also enforces the no-CDN rule inside
   `design/src`: a remote `@import` or `url()` is a failure.
3. **`scripts/check-contrast.mjs`** — the WCAG 2.2 gate. It parses the palette, the shared
   semantic tokens and both themes, resolves every `var()` chain to a literal, and computes
   a ratio for each pair the system declares: primary/secondary/muted text and links on
   canvas, pane and raised; paper ink on paper; each status foreground on its own
   background; each feedback foreground on its own background; ink on the accent fill;
   inverse text on the inverse surface; and, at 3:1, the focus ring and the visible boundary
   of a control. Every text pair is gated at 4.5:1 rather than the 3:1 that WCAG allows for
   large or bold text: the type scale is tuned for density, `display` at 28px is the only
   role that would qualify, and it uses the same ink as body text, so the allowance would
   buy nothing and cost a rule that has to be reasoned about. Decorative hairlines and
   status chip edges are printed for information and not gated — WCAG 1.4.11 asks for
   contrast on what identifies a component or its state, and a separator identifies nothing.

Because the contrast check gates rather than advises, it has shaped the system: the resting
border of an input and of a secondary button is `--rh-border-strong` rather than the lighter
separator hairline, because the edge is the only thing that says where the control is.

`pnpm --filter @research-harness/design test` runs vitest against jsdom. Every interactive
component asserts render, controlled and uncontrolled behaviour, keyboard operation, its
disabled/loading/error states, and `axe-core` with no violations. There is no browser in
this workspace, so DOM snapshots in four variants (dark/light x comfortable/compact) stand
in for screenshot regression, and `tests/tokens.test.ts` snapshots the *resolved* token maps
so a palette change shows up as a reviewable diff rather than as a silent drift.

## No CDN

Runtime rendering makes no network request for a font, an icon, a stylesheet or component
code (DS spec §12.4). Fonts are system stacks — `ui-sans-serif`/`system-ui`, `ui-serif`,
`ui-monospace` with named fallbacks — until licensed files are self-hosted, at which point
only the first entry of each stack in `src/tokens/typography.css` changes. Icons are bundled
`lucide-react` behind the `Icon` component, whose registry maps stable kebab-case names to
components so an upstream rename is absorbed in one file. KaTeX CSS and fonts, when the
manuscript and conversation surfaces need them, ship from the package rather than a CDN.

## Migrating the existing Web routes

The Web client used to style itself from a single hand-written `web/src/styles.css` with its
own `--ink` / `--line` / `--accent` variables and a light-only palette. Migration followed
the order of DS spec §9, and all five steps are done:

1. **Foundation.** Package, tokens, both themes, density, the primitives, and the two lint
   gates.
2. **Shell.** `web/src/main.tsx` imports `@research-harness/design/styles.css` before any
   application CSS and wraps the client in `ThemeProvider` (dark default) and
   `ToastProvider`; `web/src/app/Layout.tsx` composes `AppShell` + `ProjectRail`.
3. **Route by route.** Every route composes package primitives and research components.
4. **The lint flipped.** `check-tokens.mjs` fails on a raw palette value under `web/src`,
   and `web/src/styles.css` is down to layout that is genuinely application-specific.
5. **The source bundle is gone.** The Warmline prototype has been deleted; its useful
   foundations live under `design/src`.

Two things must not happen now that it is finished. A route must not keep a private copy of
a primitive that the package provides, and a route must not reintroduce a raw palette value.
Both are what the lint is for.

## Migration status

**State: complete for the v1.0 cockpit surfaces.** `pnpm --filter research-harness-web
typecheck | lint | test | build` and `pnpm --filter @research-harness/design lint | test |
build` all pass, and `web/dist` contains no `https://` reference to a font, icon or
stylesheet.

### What the Web client consumes

| Surface | Package components it composes |
|---|---|
| Shell (`app/Layout.tsx`) | `AppShell`, `ProjectRail`, `ThemeProvider`, `ToastProvider` |
| Settings (`app/SettingsDialog.tsx`) | `Dialog`, `Select` |
| Token bar (`app/TokenBar.tsx`) | `ErrorNotice`, `Input`, `Button` |
| Shared feedback (`components/Feedback.tsx`) | `AsyncState`, `ErrorNotice`, `Card`, `Badge`, `AuthorityBadge`, `ScrollArea` |
| References (`components/ObjectRef.tsx`) | `EntityRef` |
| Review actions (`components/ReviewActions.tsx`) | `ReviewDecisionBar`, `Dialog`, `Textarea`, `Button`, `useToast` |
| Source pane (`components/SourcePane.tsx`) | `SourceAnchor` (over the `web/src/pdf` adapter) |
| Every page | `FullPageWorkspace` |
| Review screen | `PaneGroup` / `Pane` / `PaneHandle`, `EvidenceCard` |
| Claims | `ClaimCard`, `ProvenancePath`, `Select`, `Input`, `Textarea` |
| Corpus | `EvidenceCard` |

### Deletions

`design/readme.md`, `design/SKILL.md`, `design/thumbnail.html`, `design/.thumbnail`,
`design/_ds_bundle.js`, `design/_ds_manifest.json`, `design/_adherence.oxlintrc.json`,
`design/styles.css` (the legacy root stylesheet, not `design/src/styles.css`),
`design/tokens/`, `design/components/`, `design/guidelines/`, `design/templates/` and
`design/ui_kits/` are removed, and `design/eslint.config.js` ignores only build output.
Nothing under `design/src`, `design/tests`, `design/specimens`, `design/scripts`, `web/` or
`vscode/` referenced any of them.

`web/src/styles.css` no longer holds a palette, a type scale, a shell grid, or a rule for a
button, an input, a badge, a panel, an error or an empty state — the package owns all of
them. What is left is application layout: the document height the shell measures against,
the shell's own slots, a compact research table, a definition row, a source quote, and the
review screen's pane frame. Every value in it is an `--rh-*` token.

### Known gaps

- **`ConflictNotice` is not used by the Conflicts page.** Its view model names two sides —
  accepted state, and what a conversation remembered — and a v1.0 conflict record is *N*
  symmetric provider positions with no accepted side. Rendering one through the other would
  print "Accepted — sent to the model" over a position nobody has accepted. The page uses
  `Card` + `Badge status="contested"` + a positions table instead. `ConflictNotice` belongs
  to W1's conversation surface, which is the case it was designed for.
- **Authority is mapped, not read.** The Design System speaks the v1.1 `AuthorityLabel`
  vocabulary; a v1.0 Claim carries an assessment `status` instead. `authorityOf()` in
  `web/src/components/Feedback.tsx` is the single place the two meet, and the daemon's own
  word is always rendered beside the badge. When the ResearchGraph carries `authority` on
  every node (G1/G2), that function becomes a pass-through.
- **`EntityRef` resolution is assumed.** Every reference the cockpit renders came out of a
  daemon listing, so it is passed as `resolved`. W3 wires `graph.resolve` and the real
  state — unresolved, stale, private, broken — flows through instead.
- **The conversation, attachment and manuscript-workspace components are unused here.**
  W1, W2 and W4 mount them; nothing in the v1.0 routes needed them.
