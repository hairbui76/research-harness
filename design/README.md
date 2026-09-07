# `@research-harness/design`

The Research Harness Design System: semantic tokens, a dark and a light theme, and the
accessible React primitives every research surface composes.

The package owns presentation and nothing else. It has no daemon client, no `fetch`, no
research rules, and no opinion about what is true — components take typed view models and
callbacks and render them. Authority over accepted scientific state stays where it has
always been, behind the capability layer (`docs/architecture/conventions.md`).

```bash
pnpm --filter @research-harness/design typecheck
pnpm --filter @research-harness/design lint       # eslint + check-tokens + check-contrast
pnpm --filter @research-harness/design test
pnpm --filter @research-harness/design build      # dist/: .js, .d.ts and every .css
```

## Consuming it

Two imports, once, at the root of the application:

```tsx
import { Button, Badge, Input } from '@research-harness/design';
import '@research-harness/design/styles.css';
```

`styles.css` is the only stylesheet a consumer links. It pulls in the palette, the token
layer, both themes, the document base and every primitive's CSS, in that order.

## Themes and density

Dark is the default and needs no attribute; light is opt-in.

```html
<html data-theme="light" data-density="compact">
```

Both attributes work on any element, not only `:root`, so a compact table can sit inside a
comfortable page and a manuscript pane can stay light inside a dark application:

```tsx
<div data-density="compact">…a dense corpus table…</div>
```

`prefers-reduced-motion: reduce` is handled in `src/tokens/motion.css`: the duration tokens
collapse to a single frame and `--rh-scale-hover` / `--rh-scale-press` become `1`, so any
component that reads the tokens is covered without writing its own media query.

## The token contract

Colour is addressed by meaning, never by value. The full list, with what each name is for,
is the comment at the top of `src/tokens/semantic.css`; the shape is:

| Group | Names |
| --- | --- |
| Surfaces | `--rh-surface-{canvas,pane,raised,paper,inverse,subtle,selected,scrim}` |
| Borders | `--rh-border-{subtle,default,strong}`, `--rh-border-on-paper`, `--rh-border-width{,-strong}` |
| Text | `--rh-text-{primary,secondary,muted,inverse,link,on-accent}`, `--rh-text-on-paper{,-secondary,-muted}` |
| Paper marks | `--rh-highlight-on-paper{,-anchor,-match}` and each one's `-border` |
| AI/action accent | `--rh-accent{,-hover,-subtle,-border,-fg,-text}` |
| Focus | `--rh-focus-ring{,-width,-offset}` |
| Scientific status | `--rh-status-<accepted\|candidate\|qualified\|contested\|stale\|private>-<fg\|bg\|border>` |
| Feedback | `--rh-feedback-<success\|error\|warning\|info>-<fg\|bg\|border>` |
| Type | `--rh-font-{sans,serif,mono}`, `--rh-type-<role>-{size,lh,ls,weight}`, `--rh-type-reading-min-size` |
| Space / radius | `--rh-space-{1,2,3,4,5,6,8,10,12,16}`, `--rh-radius-{control,nav,card,pill}` |
| Motion | `--rh-duration-{fast,base,slow}`, `--rh-ease-standard`, `--rh-scale-{hover,press}` |
| Density | `--rh-density-{row,gap,pad,font-scale}`, `--rh-control-{target-min,height-sm,height-md}` |

Three rules make the contract hold:

**Raw colour lives in two places.** `src/tokens/palette.css` and `src/themes/*.css`.
Anywhere else — a component, the Web client — is a fork of the theme that will look right
in one mode and wrong in the other. `scripts/check-tokens.mjs` fails the lint on a literal,
with an escape hatch for the genuine visualisation case:

```css
stroke: #65b5ff; /* raw-colour-ok: chart series 2, fixed across themes */
```

**The accent is not decoration.** `--rh-accent` marks model activity, the primary send/run
action, active reference tracking and selected AI provenance. It is not an emphasis colour,
not a hover colour, and it never says anything about whether a claim is true.

**Status is never colour alone.** Every one of the six scientific states renders an icon
and a label as well as its palette (`STATUS_META` in `src/primitives/Badge/status.ts`), so
the state survives greyscale, a projector, and a colour-blind reader.

`paper` is the one surface that does not follow the theme: a page of a source is near-white
in dark mode as well as light. It therefore carries its own ink. Use the `.rh-surface-paper`
utility (or `<Card surface="paper">`) rather than setting the background alone, or dark-mode
text will vanish into the page.

Anything drawn *on* a page follows the page, not the theme, for the same reason. The three
PDF evidence highlights — the SyncTeX target (`--rh-highlight-on-paper`), an accepted
anchor (`-anchor`) and a search hit (`-match`) — are paper tints of the accent, the
accepted status and the warning tone, light in both themes, each with a full-strength
`-border` of the same hue. They are painted with `mix-blend-mode: multiply` so the glyphs
stay visible through them, which is exactly why a pane tint cannot stand in: multiplied
over a near-white page, a dark-canvas tint goes to near-black and takes the page ink with
it. `scripts/check-contrast.mjs` measures each one through the blend.

## Contrast

`scripts/check-contrast.mjs` parses the token CSS, resolves every `var()` chain and
computes WCAG 2.2 ratios for each declared pair — text on each surface, each status
foreground on its own background, ink on the accent fill, the focus ring and control
boundaries. Text is gated at 4.5:1 and non-text at 3:1; decorative hairlines are reported
but not gated, and the script also checks that no scientific status has drifted close
enough to the accent to be mistaken for it. It runs in `pnpm lint` and fails the build.

A pair may say that one of its colours is painted with `mix-blend-mode: multiply` over a
third (`fgOver` / `bgOver`), and the script composites it per channel before measuring. The
paper highlights are gated that way: the page ink through each fill, and each edge against
the page. The same distance the statuses keep from the accent is required between the three
highlights as they are drawn, and between the accepted anchor and the accent itself.

```bash
node scripts/check-contrast.mjs          # the table
node scripts/check-contrast.mjs --json   # the same data, for tooling
```

Because it gates, some choices are forced: the resting border of an input or a secondary
button is `--rh-border-strong`, not the lighter hairline used for separators, because the
edge is the only thing that says where the control is.

## Type, density and the two floors

One family, one ramp, a fixed px scale — no fluid `clamp()`, because a research page is
viewed at a stable size and a title that shrank inside a pane would only look wrong there.

| Role | Size | Weight | For |
| --- | --- | --- | --- |
| `display` | 26px | 600 | the one step above a page title |
| `h1` | 22px | 600 | the page's name — every `<h1>` in the cockpit |
| `h2` | 19px | 600 | a section |
| `h3` | 16px | 600 | a panel or card header |
| `h4` | 14px | 600 | the smallest heading: body size, told apart by weight |
| `lead` | 16px | 400 | a standfirst, and the serif voice of a quotation |
| `body` | 14px | 400 | reading text |
| `body-sm` | 13px | 400 | reading text on a dense surface |
| `ui` | 13px | 500 | buttons, tabs, menu items, table headers |
| `mono` | 12px | 400 | ids, provenance, code, compiler output |
| `label` | 11px | 600 | mono, uppercase metadata chip — never a sentence |

Each heading step is about 1.16 of the one below (26/22/19/16/14), inside the 1.125–1.2 a
product interface wants: there are more type roles on a research page than on a landing
page, and stretching the ramp past that reads as noise rather than as hierarchy. The ramp
stops *at* body size. `h4` is 14px like body and separates itself by weight, because a
heading smaller than the paragraph under it inverts what a heading is for.

Two floors bound what density is allowed to do:

- `--rh-type-reading-min-size` (12px) — nothing a researcher reads renders below it on any
  surface at any density. `--rh-density-font-scale` compresses dense surfaces; a compact
  `body-sm` lands at 12.08px, and `.rh-web-table` clamps its computed size at the floor as
  well, so a future scale cannot quietly drop through it. The two roles that sit under the
  floor are not reading text: `label` is a metadata chip and `mono` is code.
- `--rh-control-target-min` (24px) — the smallest a pointer target may be (WCAG 2.2
  SC 2.5.8). Compact density takes `--rh-control-height-sm` down to exactly it, and
  `Button` and `IconButton` state it again as a `min-block-size`/`min-inline-size`, so a
  16px glyph still sits in a 24px box.

Border width is a token too, and there are two of them. `--rh-border-width` (1px) is every
separator, card edge and control boundary, and every coloured stripe down the side of a
row, a card or a notice — weight is not allowed to stand in for meaning the words and the
icon already carry. `--rh-border-width-strong` (2px) is reserved for the two marks that are
indicators rather than edges: the selected tab and the rule beside quoted matter.
`tests/tokens.test.ts` fails on a numeric border width anywhere under `design/src` or
`web/src`.

## No CDN

Nothing is fetched at runtime. Fonts are system stacks until licensed files are self-hosted
(swap the first entry of each stack in `src/tokens/typography.css`; no other change is
needed). Icons are bundled `lucide-react` behind `Icon`. `check-tokens.mjs` fails on any
remote `@import` or `url()` under `src/`.

## Layout

```text
src/
  tokens/      palette, spacing, radius, typography, motion, density, semantic
  themes/      dark.css (the default), light.css
  base.css     document reset, focus treatment, type-role utilities
  styles.css   the entry a consumer links
  primitives/  one folder per component: <Name>.tsx, <Name>.css, <Name>.test.tsx, index.ts
  utils/       cx, useControllable, ids
  hooks/       focus trap, roving tabindex, dismiss, portal, anchoring
  states/      loading / empty / partial / stale / blocked / retryable / fatal
scripts/       check-tokens.mjs, check-contrast.mjs, copy-css.mjs
tests/         setup, the axe harness, the theme x density snapshot helper, token contract
```

Primitives are grouped by what they know, not by where they appear: `Button`, `IconButton`,
`Icon`, `Badge`, `Tag`, `Card`, `Input`, `Textarea`, `Select`, `Checkbox`, `Radio`/
`RadioGroup` and `Switch` are the core and form set; the overlay, navigation and layout
primitives (`Dialog`, `Menu`, `Popover`, `Combobox`, `Tabs`, `Tooltip`, `Toast`, `Progress`,
`Skeleton`, `ScrollArea`, `ResizablePane`, `VirtualList`) sit beside them. Research,
conversation and manuscript components compose these; they never redefine them.

## Adding a component

- Strict TypeScript, `forwardRef`, typed props, no `any`. `className` and `style` pass
  through to the element a caller would expect to style.
- Controlled and uncontrolled behaviour wherever there is a value (`utils/useControllable`).
- Semantic tokens only. No literal, no hard-coded pixel gap outside the space scale.
- Give the component's stylesheet an `@import` line in `src/primitives/primitives.css`, or
  import it from the component module — `src/css.d.ts` declares the side-effect import, and
  `package.json` marks CSS as side-effectful so it survives tree shaking. The aggregator is
  preferred for anything whose cascade order matters.
- Tests cover render, controlled and uncontrolled paths, keyboard operation, the
  disabled/loading/error states, and `axe-core` through `tests/axe.ts`.
- Add `describeThemeDensitySnapshots` from `tests/variants.tsx`: four DOM snapshots
  (dark/light x comfortable/compact) stand in for screenshot regression, since there is no
  browser in this workspace.
- Icons come from the registry in `src/primitives/Icon/icons.ts` — one line per icon, so
  appending is a one-line diff. Never inline an `<svg>`.
