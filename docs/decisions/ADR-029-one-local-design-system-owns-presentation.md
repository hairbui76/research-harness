# ADR-029: One local Design System package owns presentation, and owns nothing else

**Status:** Accepted
**Date:** 2026-09-03
**Source:** PRODUCT.md §26, §42 (Q); ROADMAP.md *Cross-cutting Foundation — Research Harness Design System*, Gate DS; `docs/superpowers/specs/2026-09-03-research-harness-design-system-design.md` §1–§12; recorded in `docs/architecture/design-system.md`; implemented in `design/` (`@research-harness/design`) and consumed by `web/`

## Context

The v1.0 cockpit styled itself from one hand-written `web/src/styles.css` with its own
`--ink` / `--line` / `--accent` variables and a light-only palette, and `design/` held a
Warmline customer-support prototype: JavaScript components with inline styles, CDN fonts and
icons, no dark theme, no accessibility contract, and none of the concepts this product needs
— authority, provenance, references, attachments, manuscript state. v1.1 adds three whole
surfaces (conversation, attachments, manuscript). Building them against page-local CSS would
have produced four spellings of "candidate" and a status colour that means something
different in each route, and adopting the prototype as a runtime dependency would have
imported a CDN and a placeholder brand into a local-first product.

## Decision

`design/` is `@research-harness/design`, a strict-TypeScript package in a pnpm workspace at
the repository root (with `web/` and `vscode/`), emitting ESM, CSS, and declarations, with
React as a peer dependency. `web/` consumes it through the workspace link — `pnpm install`
at the root, not in `web/` — so a token change is visible in `pnpm dev` with no build step
between.

**The package is presentation and nothing else.** No `fetch`, no daemon client, no research
rule, no state machine over accepted objects. Components take typed view models and
callbacks; the Web client keeps the capability calls. Dependencies point one way only:
tokens and themes → primitives → research / conversation / manuscript / workspace
components → application screens.

**Colour is addressed by meaning.** Semantic tokens (`--rh-surface-*`, `--rh-text-*`,
`--rh-status-<state>-*`, `--rh-accent*`, `--rh-focus-ring*`, density, motion) resolve per
theme. Dark is the default and is declared on a bare `:root`, so a page renders correctly
before any preference is read; light is opt-in through `data-theme`, density through
`data-density`, and `prefers-reduced-motion` is handled once in the token layer. Raw palette
values are legal only under `design/src/tokens` and `design/src/themes`, and
`scripts/check-tokens.mjs` fails the lint on a literal anywhere else — **including
`web/src`**, since the migration finished — and on a remote `@import` or `url()`.
`scripts/check-contrast.mjs` resolves every `var()` chain and gates 76 declared pairs at
WCAG 2.2 AA (4.5:1 for text, 3:1 for the focus ring and a control's visible boundary),
failing rather than advising; it also checks that no status foreground has drifted close to
the AI/action accent. **Scientific status is never colour alone**: each of the six states
renders a glyph and a label, and the accent marks model activity and the primary action —
never whether something is true.

**No CDN.** Runtime rendering fetches no font, icon, stylesheet, or component code: system
font stacks until licensed files are self-hosted, bundled `lucide-react` behind a name
registry, KaTeX CSS and fonts shipped from the package.

**Migration first, deletion after.** The order of DS spec §9 was followed: package and
tokens, primitives, shell, research components, conversation/attachment components,
manuscript components, then route-by-route migration, then flipping the raw-colour lint on
`web/src` — and only then deleting the Warmline bundle (tokens, components, ui kits,
guidelines, templates, generated bundle, manifest, thumbnails). Nothing was deleted before
its replacement passed the gates.

There is no browser in this workspace, so visual regression is DOM snapshots in four
variants (dark/light × comfortable/compact) plus a snapshot of the *resolved* token maps,
and every interactive component asserts keyboard operation and `axe-core` with no
violations. That substitution is recorded as the gate's form rather than claimed to be
screenshot testing.

## Consequences

### Positive

- A button, a focus ring, and a `candidate` chip are defined once and mean the same thing
  in a conversation, a corpus table, and a manuscript pane.
- A palette change is a reviewable diff in one file plus a token snapshot, not a hunt
  through eleven routes.
- The contrast gate has shaped the system rather than described it: the resting border of
  an input and a secondary button is `--rh-border-strong`, because the edge is the only
  thing that says where the control is.
- 920 package tests pass with axe checks and per-variant snapshots, and the cockpit's own
  suite runs against the package as its only source of primitives.

### Negative / costs

- DOM snapshots catch structural and token drift, not a genuinely broken layout. Real
  screenshot regression needs a browser this environment does not have.
- Two lint scripts are project-specific tooling that has to be maintained alongside eslint.
- The package speaks the v1.1 `AuthorityLabel` vocabulary while a v1.0 Claim carries an
  assessment `status`; `authorityOf()` in `web/src/components/Feedback.tsx` is the single
  place they meet, and it stays a mapping until the graph's `authority` reaches the client.
- Some components (conversation, attachment, manuscript-workspace) are covered by their own
  tests but are only mounted by the v1.1 Web surfaces, so their integration is proven at
  the point those routes land, not before.

## Invariants this ADR protects

- One local package is the only source of primitives and theme values; a route may not fork
  a primitive or use a raw palette value (§42 Q, enforced by `check-tokens.mjs` over both
  `design/src` and `web/src`).
- Runtime makes no CDN request for a font, icon, stylesheet, or component (§42 Q; PRODUCT
  §34's local-first boundary).
- Semantic status is distinguishable without colour, and the AI/action accent never encodes
  scientific truth (PRODUCT §26).
- Dark and light preserve the same semantic meanings and both meet WCAG 2.2 AA on every
  declared pair.
- A design component never calls the daemon, mutates canonical state, or invokes a provider
  (ADR-004: the layer that draws a decision is not the layer allowed to make it).
- The theme preference is local UI state with no effect on canonical state, `.research/`,
  or anything a model is sent.

## Rejected alternatives

- **Keep styling each route locally.** What v1.0 did; three new surfaces would have made
  it four dialects of the same vocabulary.
- **Adopt an off-the-shelf component library.** Brings a theme system, an accessibility
  story, and a release cadence that are all someone else's, and none of the research
  semantics — which is the half that matters here.
- **Import the Warmline bundle and restyle it.** Prototype JSX with inline styles and CDN
  assets; the useful parts were the warm-neutral foundation, the spacing discipline, and
  the three-pane composition, and those were translated rather than imported.
- **Keep the prototype tree around "for reference".** DS spec §11: a permanent legacy tree
  with no testing or documentation purpose is a second source of truth that drifts.
- **Advise on contrast instead of gating.** An advisory check is a warning nobody reads at
  the moment a token is changed.
- **Ship a third theme or a theming API.** No measured need; two themes already cost two
  full contrast surfaces.

## Where it is enforced

- `design/package.json` (exports, peer React, `lint` = eslint + tokens + contrast),
  `pnpm-workspace.yaml`, `package.json` at the repository root.
- `design/src/tokens/*`, `design/src/themes/{dark,light}.css`, `design/src/base.css`,
  `design/src/styles.css` (the single stylesheet).
- `design/scripts/check-tokens.mjs` (raw-palette and no-CDN lint, applied to `design/src`
  *and* `web/src`), `design/scripts/check-contrast.mjs` (WCAG gate, status/accent
  separation).
- `design/src/primitives/Badge/status.ts` (`STATUS_META`: glyph and label per state),
  `design/src/workspace/ThemeProvider`, `design/src/primitives/Icon/icons.ts`.
- `design/tests/tokens.test.ts` (resolved token snapshots), `design/tests/axe.ts`,
  `design/tests/variants.tsx`, and each component's `*.test.tsx` and `__snapshots__/`.
- `web/src/main.tsx` (one stylesheet import), `web/src/app/Layout.tsx`, `web/src/app/routes.tsx`,
  `web/src/styles.css` (application layout only, every value an `--rh-*` token).
- `docs/architecture/design-system.md` records the consumption map, the gates, and the
  known gaps.
