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

   The same rule is applied to `web/src`, where findings currently print as **warnings**.
   The Web client migrates route by route; the migration task turns those warnings into
   failures once the last route is on the package. The script also enforces the no-CDN rule
   inside `design/src`: a remote `@import` or `url()` is a failure.
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

The Web client currently styles itself from a single hand-written `web/src/styles.css` with
its own `--ink` / `--line` / `--accent` variables and a light-only palette. Migration is
incremental so research screens stay usable throughout, and follows the order in DS spec §9:

1. **Foundation** (done). Package, tokens, both themes, density, the primitives, and the two
   lint gates.
2. **Shell.** `web/src/main.tsx` imports `@research-harness/design/styles.css`;
   `web/src/app/Layout.tsx` composes the Design System shell, and the theme and density
   preferences are read from local storage and written to `data-theme` / `data-density` on
   the document element.
3. **Route by route**, in this order — the busiest screens first, so the shared components
   are exercised early: `EvidenceReview`, `ReviewInbox`, `Overview`, `Claims`, `Corpus`,
   `Conflicts`, `Stale`, `Questions`, `Synthesis`, `Taxonomy`, `Manuscript`. Each route
   swaps its local markup for package primitives, deletes the rules it no longer needs from
   `web/src/styles.css`, and keeps its existing tests green.
4. **Flip the lint.** When `web/src` reports no raw-colour warnings, `check-tokens.mjs`
   starts failing on them, and `web/src/styles.css` is reduced to layout that is genuinely
   application-specific.
5. **Delete the source bundle.** The Warmline prototype (`design/readme.md`,
   `design/tokens/`, `design/components/`, `design/ui_kits/`, `design/guidelines/`,
   `design/templates/`, `design/styles.css` and the generated bundle/manifest/thumbnail
   artefacts) is a design input, not a runtime dependency. It is removed once its useful
   foundations — the warm-neutral palette, the typography roles, the spacing and radius
   discipline, the semantic-token idea and the three-pane composition — have production
   replacements that pass these gates.

Two things must not happen during the migration. A route must not keep a private copy of a
primitive that the package now provides, and a route must not reintroduce a raw palette
value to "match" a screen that has not migrated yet. Both are what the lint is for.
