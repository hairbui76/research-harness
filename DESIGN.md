---
name: Research Harness
description: A warm, dense, editorial research cockpit where the model's accent never says whether a claim is true.
colors:
  # Warm neutral ramp (design/src/tokens/palette.css). Every step is read by a theme;
  # scripts/token-usage.mjs fails on one that is not.
  warm-1000: "#0e0d0c"
  warm-975: "#141312"
  warm-950: "#1b1a18"
  warm-900: "#232120"
  warm-850: "#2b2926"
  warm-800: "#33302c"
  warm-750: "#3d3a35"
  warm-700: "#4a4640"
  warm-600: "#635e56"
  warm-500: "#7d776e"
  warm-400: "#a49d93"
  warm-300: "#c9c2b8"
  warm-200: "#dedbd6"
  warm-150: "#e7e3dc"
  warm-100: "#ece8e2"
  warm-75: "#f2efe9"
  warm-50: "#faf9f6"
  white: "#ffffff"
  off-black: "#111111"
  # The reading surface and its own ink. Near-white in BOTH themes.
  paper: "#f8f7f4"
  paper-ink: "#1a1815"
  paper-ink-secondary: "#4d483f"
  paper-ink-muted: "#6b6558"
  paper-line: "#ded9cf"
  # Marks drawn on the page with mix-blend-mode: multiply.
  paper-mark: "#ffb694"
  paper-mark-anchor: "#9fdfb0"
  paper-mark-match: "#f4c32f"
  # AI / action accent. Model activity, send/run, active reference tracking, AI provenance.
  accent-700: "#b83a00"
  accent-600: "#d94800"
  accent-500: "#ff5600"
  accent-400: "#ff7331"
  accent-300: "#ff9057"
  accent-tint-dark: "#3a1d0e"
  accent-tint-light: "#ffe9dd"
  accent-edge-dark: "#6d3717"
  accent-edge-light: "#ffcbaf"
  # Six scientific status families: accepted, candidate, qualified, contested, stale, private.
  green-700: "#1a6330"
  green-300: "#93d8a3"
  green-tint-light: "#e4f2e7"
  green-tint-dark: "#14281a"
  green-edge-light: "#b6dabf"
  green-edge-dark: "#2f5a3c"
  blue-700: "#1a4f7a"
  blue-300: "#93c6ec"
  blue-tint-light: "#e4eef7"
  blue-tint-dark: "#11202d"
  blue-edge-light: "#b3d0e7"
  blue-edge-dark: "#2c4d68"
  violet-700: "#57368a"
  violet-300: "#c4abec"
  violet-tint-light: "#eee8f7"
  violet-tint-dark: "#201a31"
  violet-edge-light: "#cfc0e6"
  violet-edge-dark: "#463a63"
  red-700: "#9c2019"
  red-300: "#f2a79f"
  red-tint-light: "#fbe8e6"
  red-tint-dark: "#2e1512"
  red-edge-light: "#eec1bb"
  red-edge-dark: "#6b302a"
  ochre-700: "#74561a"
  ochre-300: "#dcc082"
  ochre-tint-light: "#f5eedd"
  ochre-tint-dark: "#2a2212"
  ochre-edge-light: "#decfa8"
  ochre-edge-dark: "#5a4a26"
  slate-700: "#3b4653"
  slate-300: "#b0bbc7"
  slate-tint-light: "#ebeef2"
  slate-tint-dark: "#191d22"
  slate-edge-light: "#cbd3db"
  slate-edge-dark: "#3a444f"
  # Feedback-only hue (warning). Success, error and info reuse green, red and blue.
  amber-700: "#7d5300"
  amber-300: "#eebe6a"
  amber-tint-light: "#fbf0da"
  amber-tint-dark: "#2c2210"
  amber-edge-light: "#e6d3a5"
  amber-edge-dark: "#5c4720"
  # Scrims: the only transparency in the system.
  scrim-dark: "rgba(8, 7, 6, 0.66)"
  scrim-light: "rgba(26, 24, 21, 0.42)"
typography:
  display:
    fontFamily: "ui-sans-serif, system-ui, -apple-system, 'Segoe UI', Roboto, 'Helvetica Neue', Arial, 'Noto Sans', sans-serif"
    fontSize: "26px"
    fontWeight: 600
    lineHeight: 1.15
    letterSpacing: "-0.5px"
  h1:
    fontFamily: "ui-sans-serif, system-ui, -apple-system, 'Segoe UI', Roboto, 'Helvetica Neue', Arial, 'Noto Sans', sans-serif"
    fontSize: "22px"
    fontWeight: 600
    lineHeight: 1.2
    letterSpacing: "-0.35px"
  h2:
    fontFamily: "ui-sans-serif, system-ui, -apple-system, 'Segoe UI', Roboto, 'Helvetica Neue', Arial, 'Noto Sans', sans-serif"
    fontSize: "19px"
    fontWeight: 600
    lineHeight: 1.25
    letterSpacing: "-0.2px"
  h3:
    fontFamily: "ui-sans-serif, system-ui, -apple-system, 'Segoe UI', Roboto, 'Helvetica Neue', Arial, 'Noto Sans', sans-serif"
    fontSize: "16px"
    fontWeight: 600
    lineHeight: 1.3
    letterSpacing: "-0.1px"
  h4:
    fontFamily: "ui-sans-serif, system-ui, -apple-system, 'Segoe UI', Roboto, 'Helvetica Neue', Arial, 'Noto Sans', sans-serif"
    fontSize: "14px"
    fontWeight: 600
    lineHeight: 1.35
    letterSpacing: "normal"
  lead:
    fontFamily: "ui-serif, Charter, 'Iowan Old Style', Georgia, Cambria, 'Times New Roman', Times, serif"
    fontSize: "16px"
    fontWeight: 400
    lineHeight: 1.5
    letterSpacing: "normal"
  body:
    fontFamily: "ui-sans-serif, system-ui, -apple-system, 'Segoe UI', Roboto, 'Helvetica Neue', Arial, 'Noto Sans', sans-serif"
    fontSize: "14px"
    fontWeight: 400
    lineHeight: 1.5
    letterSpacing: "normal"
  body-sm:
    fontFamily: "ui-sans-serif, system-ui, -apple-system, 'Segoe UI', Roboto, 'Helvetica Neue', Arial, 'Noto Sans', sans-serif"
    fontSize: "13px"
    fontWeight: 400
    lineHeight: 1.45
    letterSpacing: "normal"
  ui:
    fontFamily: "ui-sans-serif, system-ui, -apple-system, 'Segoe UI', Roboto, 'Helvetica Neue', Arial, 'Noto Sans', sans-serif"
    fontSize: "13px"
    fontWeight: 500
    lineHeight: 1.4
    letterSpacing: "normal"
  label:
    fontFamily: "ui-monospace, SFMono-Regular, 'SF Mono', Menlo, Consolas, 'Liberation Mono', 'Courier New', monospace"
    fontSize: "11px"
    fontWeight: 600
    lineHeight: 1.25
    letterSpacing: "0.08em"
  mono:
    fontFamily: "ui-monospace, SFMono-Regular, 'SF Mono', Menlo, Consolas, 'Liberation Mono', 'Courier New', monospace"
    fontSize: "12px"
    fontWeight: 400
    lineHeight: 1.5
    letterSpacing: "normal"
rounded:
  mark: "2px"
  control: "4px"
  nav: "6px"
  card: "8px"
  pill: "999px"
spacing:
  "1": "4px"
  "2": "8px"
  "3": "12px"
  "4": "16px"
  "5": "20px"
  "6": "24px"
  "8": "32px"
  "10": "40px"
  "12": "48px"
  "16": "64px"
components:
  # Colour refs below are the dark theme (the default). design/src/themes/light.css remaps
  # the same semantic names; see Colors for the light values.
  button-primary:
    backgroundColor: "{colors.warm-100}"
    textColor: "{colors.warm-975}"
    typography: "{typography.ui}"
    rounded: "{rounded.control}"
    padding: "0 12px"
    height: "32px"
  button-primary-hover:
    backgroundColor: "{colors.warm-100}"
    textColor: "{colors.warm-975}"
  button-secondary:
    backgroundColor: "{colors.warm-900}"
    textColor: "{colors.warm-100}"
    typography: "{typography.ui}"
    rounded: "{rounded.control}"
    padding: "0 12px"
    height: "32px"
  button-secondary-hover:
    backgroundColor: "{colors.warm-850}"
    textColor: "{colors.warm-100}"
  button-ghost:
    textColor: "{colors.warm-300}"
    typography: "{typography.ui}"
    rounded: "{rounded.control}"
    padding: "0 12px"
    height: "32px"
  button-ghost-hover:
    backgroundColor: "{colors.warm-850}"
    textColor: "{colors.warm-100}"
  button-danger:
    backgroundColor: "{colors.red-tint-dark}"
    textColor: "{colors.red-300}"
    typography: "{typography.ui}"
    rounded: "{rounded.control}"
    padding: "0 12px"
    height: "32px"
  button-accent:
    backgroundColor: "{colors.accent-500}"
    textColor: "{colors.warm-1000}"
    typography: "{typography.ui}"
    rounded: "{rounded.control}"
    padding: "0 12px"
    height: "32px"
  button-accent-hover:
    backgroundColor: "{colors.accent-400}"
    textColor: "{colors.warm-1000}"
  button-sm:
    typography: "{typography.body-sm}"
    rounded: "{rounded.control}"
    padding: "0 8px"
    height: "26px"
  icon-button:
    rounded: "{rounded.control}"
    padding: "0"
    size: "32px"
  input:
    backgroundColor: "{colors.warm-950}"
    textColor: "{colors.warm-100}"
    typography: "{typography.body}"
    rounded: "{rounded.control}"
    padding: "0 12px"
    height: "32px"
  input-sm:
    typography: "{typography.body-sm}"
    rounded: "{rounded.control}"
    padding: "0 8px"
    height: "26px"
  badge:
    backgroundColor: "{colors.warm-850}"
    textColor: "{colors.warm-300}"
    typography: "{typography.body-sm}"
    rounded: "{rounded.control}"
    padding: "2px 8px"
  badge-status-accepted:
    backgroundColor: "{colors.green-tint-dark}"
    textColor: "{colors.green-300}"
    rounded: "{rounded.control}"
    padding: "2px 8px"
  badge-status-candidate:
    backgroundColor: "{colors.blue-tint-dark}"
    textColor: "{colors.blue-300}"
    rounded: "{rounded.control}"
    padding: "2px 8px"
  badge-status-qualified:
    backgroundColor: "{colors.violet-tint-dark}"
    textColor: "{colors.violet-300}"
    rounded: "{rounded.control}"
    padding: "2px 8px"
  badge-status-contested:
    backgroundColor: "{colors.red-tint-dark}"
    textColor: "{colors.red-300}"
    rounded: "{rounded.control}"
    padding: "2px 8px"
  badge-status-stale:
    backgroundColor: "{colors.ochre-tint-dark}"
    textColor: "{colors.ochre-300}"
    rounded: "{rounded.control}"
    padding: "2px 8px"
  badge-status-private:
    backgroundColor: "{colors.slate-tint-dark}"
    textColor: "{colors.slate-300}"
    rounded: "{rounded.control}"
    padding: "2px 8px"
  badge-tone-accent:
    backgroundColor: "{colors.accent-tint-dark}"
    textColor: "{colors.accent-300}"
    rounded: "{rounded.control}"
    padding: "2px 8px"
  tag:
    backgroundColor: "{colors.warm-900}"
    textColor: "{colors.warm-300}"
    typography: "{typography.body-sm}"
    rounded: "{rounded.pill}"
    padding: "0 12px"
    height: "26px"
  tag-selected:
    backgroundColor: "{colors.warm-800}"
    textColor: "{colors.warm-100}"
    rounded: "{rounded.pill}"
  card:
    backgroundColor: "{colors.warm-900}"
    textColor: "{colors.warm-100}"
    rounded: "{rounded.card}"
    padding: "12px 16px"
  card-pane:
    backgroundColor: "{colors.warm-950}"
    textColor: "{colors.warm-100}"
    rounded: "{rounded.card}"
    padding: "12px 16px"
  card-paper:
    backgroundColor: "{colors.paper}"
    textColor: "{colors.paper-ink}"
    rounded: "{rounded.card}"
    padding: "12px 16px"
  tab:
    textColor: "{colors.warm-300}"
    typography: "{typography.ui}"
    rounded: "{rounded.nav}"
    padding: "8px 12px"
    height: "36px"
  tab-selected:
    textColor: "{colors.warm-100}"
    typography: "{typography.ui}"
  nav-item:
    textColor: "{colors.warm-300}"
    typography: "{typography.ui}"
    rounded: "{rounded.nav}"
    padding: "0 8px"
    height: "36px"
  nav-item-hover:
    backgroundColor: "{colors.warm-850}"
    textColor: "{colors.warm-100}"
  nav-item-active:
    backgroundColor: "{colors.warm-800}"
    textColor: "{colors.warm-100}"
  menu:
    backgroundColor: "{colors.warm-900}"
    textColor: "{colors.warm-100}"
    typography: "{typography.ui}"
    rounded: "{rounded.card}"
    padding: "4px"
  menu-item:
    rounded: "{rounded.nav}"
    padding: "8px 12px"
    height: "36px"
  dialog:
    backgroundColor: "{colors.warm-900}"
    textColor: "{colors.warm-100}"
    rounded: "{rounded.card}"
    padding: "24px"
  toast:
    backgroundColor: "{colors.warm-900}"
    textColor: "{colors.warm-100}"
    rounded: "{rounded.card}"
    padding: "12px 16px"
    width: "26rem"
---

# Design System: Research Harness

## Overview

**Creative North Star: "Ink on Warm Paper"**

The cockpit is a research instrument, not a landing page. Its whole surface is one warm
neutral ramp: every grey carries a little red and yellow so the default dark canvas reads
as ink on paper rather than as a cold console, and the selectable light theme is the same
cream-and-white foundation the other way up. Inside that ramp sits one surface that
refuses to follow the theme: `paper`, the near-white page a source or manuscript is read
on, which brings its own dark ink and its own light marks in both modes because a page of
a paper is a page of a paper.

Colour is spent on meaning and almost nowhere else. One orange accent belongs to the model
and to the primary action (send, run, active reference tracking, AI provenance) and never
says whether a claim is true. Six separate scientific status families (accepted,
candidate, qualified, contested, stale, private) carry scientific authority, always with a
glyph and a word beside the tint. Four feedback tones carry transient application state.
Everything else is the ramp. Depth is a hairline and a surface change, never a shadow;
motion is two durations and a 2% scale, reserved for direct manipulation.

The system is dense and editorial. A fixed sans ramp of 26/22/19/16/14 with a step of
about 1.16 tops out at the page title and bottoms out at body size; a serif carries quoted
source matter; a mono carries ids, provenance and code. Two floors bound what density may
do: nothing a researcher reads renders under 12px, and nothing a pointer must hit is
smaller than 24px.

**Key Characteristics:**
- One warm ramp, two themes, zero cool greys; dark is the default.
- A reading surface (`paper`) that is near-white in both themes and owns its own ink.
- The accent is the model's; scientific status is six families that are never colour alone.
- Depth is a 1px hairline plus a surface step; the only shadow belongs to overlays.
- Fixed px type ramp 26/22/19/16/14, ~1.16 between steps, `h4` at body size told apart by weight.
- Two border widths (1px and 2px), two durations (120ms and 200ms), a 4px spacing base.
- Nothing is fetched at runtime: system font stacks, bundled icons, no CDN.

## Colors

A warm neutral ramp carries the whole interface; one reserved accent and six status hues are
the only chroma, each held to WCAG AA on its own tint by `design/scripts/check-contrast.mjs`.

### Primary
- **Model Orange** (`accent-500`, `#ff5600`): the AI/action accent. Fills the send/run
  button, the selected tab's 2px marker and an active reference-tracking state. Ink on
  it is `warm-1000`. Hover moves one step: `accent-400` in dark, `accent-600` in light.
- **Accent as text** (`accent-300` in dark, `accent-700` in light): the accent as ink on a
  normal surface, gated at 4.5:1. Used for a followed reference's label and an accent badge.
- **Accent tint and edge** (`accent-tint-dark`/`accent-edge-dark` in dark;
  `accent-tint-light`/`accent-edge-light` in light): the fill and hairline of an accent
  badge or a selected evidence card. Marks "this came from, or is about, a model call".

### Secondary
The six scientific status families. Each is a `-fg`, `-bg`, `-border` triple; dark reads
the `300` ink on the `tint-dark` fill with the `edge-dark` hairline, light reads the `700`
ink on `tint-light` with `edge-light`.
- **Accepted, green** (`green-300` / `green-700`): reviewed, part of accepted state.
- **Candidate, blue** (`blue-300` / `blue-700`): proposed, awaiting review.
- **Qualified, violet** (`violet-300` / `violet-700`): accepted with a stated condition.
- **Contested, red** (`red-300` / `red-700`): conflicting evidence on record.
- **Stale, ochre** (`ochre-300` / `ochre-700`): source or anchor moved since recording.
- **Private, slate** (`slate-300` / `slate-700`): local only.

### Tertiary
Application feedback, transient and never scientific. Success, error and info reuse the
green, red and blue families above; **Warning, amber** (`amber-300` / `amber-700`, tints
and edges likewise) is the one hue that exists only for feedback. Feedback tints the whole
hairline of a notice or toast and colours its icon; the tone is also written in words.

### Neutral
Dark theme (default):
- **Canvas** (`warm-975`): the application background.
- **Pane** (`warm-950`): the rail, inspector, page header, input fill.
- **Raised** (`warm-900`): cards, menus, popovers, dialogs, toasts.
- **Subtle** (`warm-850`): hover tint and the subtle hairline.
- **Selected** (`warm-800`): the selected row, nav item, tag or text selection.
- **Hairlines** (`warm-850` subtle, `warm-750` default, `warm-500` strong): strong is the
  3:1 edge of inputs and secondary buttons; the other two are decorative separators.
- **Ink** (`warm-100` primary and link, `warm-300` secondary, `warm-400` muted): muted is
  held one step brighter than the ramp would suggest so it passes 4.5:1 on the selected row.
- **Inverse band** (`warm-100` surface, `warm-975` ink): the primary button.
- **Focus ring** (`warm-150`).

Light theme (selectable):
- **Canvas** (`warm-50`), **Pane and Raised** (`white`), **Subtle** (`warm-75`),
  **Selected** (`warm-150`).
- **Hairlines** (`warm-150` subtle, `warm-200` default, `warm-500` strong).
- **Ink** (`off-black` primary and link, `warm-700` secondary, `warm-600` muted).
- **Inverse band** (`warm-975` surface, `warm-100` ink). **Focus ring** (`warm-1000`).

Both themes:
- **Paper** (`paper` in dark, `white` in light) with **Paper ink** (`paper-ink`,
  `paper-ink-secondary`, `paper-ink-muted`) and **Paper line** (`paper-line`): the reading
  surface and its own text, applied together through `.rh-surface-paper`.
- **Paper marks** (`paper-mark`, `paper-mark-anchor`, `paper-mark-match`): the SyncTeX
  target, an accepted anchor and a search hit, painted with `mix-blend-mode: multiply` and
  edged with `accent-700`, `green-700` and `amber-700` at full strength.
- **Scrim** (`scrim-dark` / `scrim-light`): the flat wash behind a drawer or dialog; the
  only alpha in the system.

### Named Rules
**The Model's Orange Rule.** The accent marks model activity, the primary send/run action,
active reference tracking and selected AI provenance. It is not an emphasis colour, not a
hover colour, not a link colour, not a navigation colour — which tab you are on and which
option the keyboard is on are both said in ink — and it never says anything about whether a
claim is true.

**The Third Channel Rule.** A scientific status renders a glyph and a label before it
renders a tint. Every status and feedback tone must survive greyscale; a border colour or a
fill is never the only signal.

**The Two Homes Rule.** A colour literal may appear in `palette.css` and the two theme files
and nowhere else. Every component and every cockpit stylesheet addresses colour by semantic
name (`--rh-surface-*`, `--rh-text-*`, `--rh-status-*`); the lint fails on a literal.

**The Paper Keeps Its Ink Rule.** Anything drawn on the reading surface follows the page,
not the theme: the paper's ink is dark and its marks are light in both modes, and the
surface is always applied together with its ink, never as a background alone.

## Typography

**Display Font:** system sans (`ui-sans-serif, system-ui, -apple-system, 'Segoe UI', Roboto, 'Helvetica Neue', Arial, 'Noto Sans', sans-serif`)
**Body Font:** the same system sans
**Editorial Font:** system serif (`ui-serif, Charter, 'Iowan Old Style', Georgia, Cambria, 'Times New Roman', Times, serif`)
**Label/Mono Font:** system mono (`ui-monospace, SFMono-Regular, 'SF Mono', Menlo, Consolas, 'Liberation Mono', 'Courier New', monospace`)

**Character:** One family, one fixed ramp, no `clamp()`. The sans is the instrument; the
serif appears only where a source is quoted or a manuscript is read; the mono is for
anything a machine wrote or a researcher copies. All three are system stacks so the runtime
makes no network request; a licensed face replaces the first entry of a stack and nothing else.

### Hierarchy
- **Display** (600, 26px, 1.15, -0.5px): the one step above a page title. Published for
  hosts; the cockpit itself sets no display type, every page title is an `h1`.
- **H1** (600, 22px, 1.2, -0.35px): the page's name. Every `<h1>` in the cockpit, on every
  workspace, is this size.
- **H2** (600, 19px, 1.25, -0.2px): a section.
- **H3** (600, 16px, 1.3, -0.1px): a panel or card header.
- **H4** (600, 14px, 1.35): the smallest heading. Body size, told apart by weight; also the
  dialog title, the evidence card's name and the narrow shell bar's title.
- **Lead** (400, 16px, 1.5): a standfirst, and in the serif, the voice of a quotation
  (the evidence card's quote, the review screen's source span).
- **Body** (400, 14px, 1.5): reading text: conversation turns, evidence quotes, reasons,
  descriptions, a field's error sentence. Prose is capped at 68ch (`--rh-measure-prose`);
  tables, code, source quotes and the PDF pane are not.
- **Body-sm** (400, 13px, 1.45): reading text on a dense surface: a queue row, a table
  cell, a badge's word, a toast's title.
- **UI** (500, 13px, 1.4): buttons, tabs, menu items, field labels, the rail.
- **Label** (600, 11px, 1.25, 0.08em, uppercase, mono): a metadata chip such as a menu
  group label or a `<dt>`. Never a sentence, never a lead-in above a heading.
- **Mono** (400, 12px, 1.5): ids, provenance, code, compiler output, counts in a pill.

### Named Rules
**The Reading Floor Rule.** Nothing a researcher reads renders under 12px
(`--rh-type-reading-min-size`) on any surface at any density. Compact density multiplies
type by 0.929, so `body-sm` lands at 12.08px; tables and small badges clamp with `max()`
so a future scale cannot drop through. The two roles under the floor, `label` and `mono`,
are metadata, not reading text.

**The Heading Stops at Body Rule.** The ramp is 26/22/19/16/14, about 1.16 between
neighbours, and it bottoms out at body size. A heading is never set smaller than the
paragraph it introduces; `h4` separates itself by weight alone.

**The Label Is Not a Kicker Rule.** The 11px uppercase mono role names a group, a column or
a definition term. Set before a sentence or above a heading it is a kicker, and the build
removed every one of those; a tone or a kind is written as the first words of the title in
the title's own type instead.

## Layout

The shell is a three-pane row on a full-height document: a 16rem project rail on the left
(`pane` surface, 1px right hairline), the route in the centre, and a 26rem research
inspector on the right capped at 40% of the shell (`pane` surface, 1px left hairline).
Below 960px viewport width both side panes become drawers (`min(20rem, 85vw)`) over a
scrim, and a narrow bar appears above the route with the title at `h4`.

Pages are query containers, not viewport listeners: a research page has to fit whatever a
rail, an inspector and a draggable divider leave it, so `FullPageWorkspace` queries its own
inline size (`rh-page`, narrow below 44rem: the toolbar drops under the title and the 20rem
side column goes under the content), and the inspector queries its own (`rh-inspector`,
narrow below 20rem). The manuscript workspace measures its own inline size the same way
and switches its whole arrangement below 960px - three columns become the file tree beside
one tab strip, where the source, the PDF and the audit inspector take turns over the
document area - because on a 1024px screen the shell's rail leaves it about 768px and a
viewport query would call that wide; the diagnostics panel inside it queries its own width
too (`rh-diagnostics`, narrow below 34rem: a row's message takes a line of its own rather
than a few characters beside a fixed file position). The shell keeps its viewport query
because the shell is the window. Every overlay portals to `document.body`, which is what
makes containment safe.

A full page keeps its frame in every state: a sticky header (padding 16px 20px 12px, 1px
bottom hairline, the `h1`, its description in secondary ink and its toolbar) above a body
padded 16px 20px, with an optional 12px-padded footer. Loading fills the body with
skeletons in the shape of what is coming; an empty state names a next action.

Spacing sits on a 4px base and the token name is the multiplier (`space-3` = 12px). The
rhythm in use is 8px between controls and chips on a row, 12px between list items and
inside a card's small padding, 16px between stacked panels and as page padding, 24px inside
a dialog. Zero is written as `0`, never as a token. Sub-scale 2px appears only as an
optical nudge (an icon to a baseline, a badge's vertical padding); it is not a spacing step.

Density is geometry, not a second type scale. Comfortable (default) rows are 36px with an
8px gap and 12px inline padding; compact rows are 28px with a 4px gap and 8px padding, and
compact takes the medium control to 28px and the small control to the 24px target floor.
The attribute works on any element, so a compact table sits inside a comfortable page.

Viewport breakpoints observed: 1100px (the review screen's source/decision split stacks),
960px (shell drawers), 768px (the toast strip takes full width), 640px (definition rows and
settings forms collapse to one column).

## Elevation & Depth

Flat by construction. Depth is a warm hairline plus a step on the surface ramp: canvas
under pane under raised, each one step lighter in dark and white-on-cream in light. Cards,
menus, popovers, dialogs and toasts are all `raised` with a 1px `default` or `subtle`
hairline and no shadow. Hover on a card moves the hairline to `strong`, not the surface.

### Shadow Vocabulary
- **Overlay** (`box-shadow: 0 16px 40px rgba(6, 5, 4, 0.55)` in dark;
  `0 16px 40px rgba(26, 24, 21, 0.16)` in light; `--rh-shadow-overlay`): the one soft
  shadow, on a drawer panel that slides over the page beside a scrim.

### Named Rules
**The Hairline Is the Edge Rule.** Two border widths ship and no more. 1px is every
separator, card edge, control boundary and coloured notice hairline. 2px is reserved for
the two marks that are indicators rather than edges: the selected tab's marker and the rule
beside quoted matter. A coloured stripe down the side of a card, a row or a notice takes
the hairline; the tone tints the whole edge.

**The Edge That Locates Rule.** The resting border of an input or a secondary button is
`strong` (3:1 against its surface) because the edge is the only thing that says where the
control is; decorative separators use the lighter hairlines and are reported, not gated.

## Shapes

Near-rectangular controls on soft warm surfaces. Radius is three steps and a pill: 4px on
controls, badges, inputs, notices and the skip link; 6px on nav items, menu items, tabs
(top corners only) and combobox options; 8px on cards, dialogs, menus and toasts. The pill
(999px) is reserved for what is genuinely round: avatars, count pips in the rail and
inspector tabs, removable tags, and the text-shaped skeleton bar. Nothing else is rounded
past 8px.

Borders are always solid, 1px, on the semantic hairline tokens; the only dashed rule is the
hairline above a decision prompt. Tabs draw their 2px marker in primary ink on the bottom
(or right, when vertical) edge of a 6px-topped tab. Quoted matter carries a 2px `strong`
(review screen) or `default` (evidence card, conflict notice) rule on its start edge with
12px inset; a stale quote turns that rule the stale status border.

## Components

### Buttons
- **Character:** quiet, edge-defined, monochrome until the model acts.
- **Shape:** near-square (4px), 32px tall at medium, 26px small, 1px border (transparent
  unless the variant needs an edge), `ui` type scaled by density.
- **Primary:** the inverse band (`surface-inverse` fill, `text-inverse` ink; hover to
  `text-primary`). Padding 0 12px.
- **Secondary:** `raised` fill with a `strong` hairline; hover to `subtle` fill and a
  `text-primary` edge.
- **Ghost:** transparent, secondary ink; hover to `subtle` fill and primary ink.
- **Danger:** error tint, error edge, error ink; hover strengthens the edge to the ink.
- **Accent:** the model's orange with `warm-1000` ink; hover one step to `accent-hover`.
  Send, run, model activity only.
- **Hover / Press:** `scale(1.02)` and `scale(0.98)` over 120ms with the standard ease;
  colour changes are linear at 120ms. Disabled is 0.55 opacity with `not-allowed`.
  Loading hides the content and spins a bundled icon (900ms, stopped under reduced motion).
- **Icon button:** a 32px (small 26px) square, never under the 24px target floor, sharing
  every variant above.

### Chips
- **Badge:** a word of one of the daemon's vocabularies. `subtle` fill, `default` hairline,
  secondary ink, `body-sm` at `ui` weight, 2px 8px padding, 4px corners; height comes from
  the text so it sits inside a line of prose. Six `status-*` variants and five `tone-*`
  variants (success, error, warning, info, accent) swap fill, edge and ink together, and
  every status renders its glyph and label from `STATUS_META`. The small badge floors its
  size at 12px.
- **Tag:** the one pill. `raised` fill, `default` hairline, 26px body at 0 12px; selected
  moves to `selected` fill and `strong` edge; the remove button sits behind a 1px left
  hairline and turns error-tinted on hover; focus rings draw inside the pill.

### Cards / Containers
- **Corner Style:** 8px.
- **Background:** `raised` by default; `pane` variant when the card sits on a raised
  surface; `paper` variant for a source page, which brings its own ink and `paper-line` edge.
- **Shadow Strategy:** none; a 1px `subtle` hairline. Hoverable cards move it to `strong`.
- **Internal Padding:** small 8px 12px, medium 12px 16px, large 16px 24px, applied to each
  section; header is `h3` above a bottom hairline, footer is muted `body-sm` below a top one.
- **Selected evidence** takes the accent edge; a stale card turns its quote rule ochre.

### Inputs / Fields
- **Style:** `pane` fill, 1px `strong` stroke (the edge is what locates the control), 4px
  corners, 32px tall (26px small), 0 12px padding, `body` type scaled by density, muted
  placeholder. A leading icon sits at the padding and pushes the text by 20px.
- **Focus:** the system ring, 2px `focus-ring` at 2px offset; components never remove it,
  and one that needs it inside sets the offset negative instead.
- **Hover:** the stroke moves to `text-primary`.
- **Error / Disabled:** `aria-invalid` turns the stroke to the error edge and the field
  shows an icon plus a sentence at `body` size in error ink; disabled is `subtle` fill at
  0.65 opacity. Labels are `ui`; descriptions are muted `body-sm`; the required mark is
  error ink.

### Navigation
- **Rail:** 16rem, `pane` surface, `ui` type, 8px padding. Nav items are 36px rows at
  0 8px with 6px corners, secondary ink; hover to `subtle` fill and primary ink; the current
  page takes `selected` fill, primary ink and `ui` weight. Counts sit in a mono pill with a
  `subtle` hairline, inset 1px block and 8px inline — one hairline's worth of block room, so
  the pill has an inside while its height still comes from the text and never sets the row's.
  A top hairline separates the nav from the session list; the provider's standing sits in the
  foot in feedback ink with the word beside it.
- **Tabs:** `ui` type on a 36px-minimum tab padded 8px 12px, secondary ink over a strip
  with a bottom hairline. Hover to `subtle` fill and primary ink; selected is primary ink
  with a 2px marker in that same ink on the bottom edge (right edge when vertical) — a tab
  strip is navigation, and navigation is never where the accent is spent. A strip that
  overflows fades its clipped end over 48px and shows a scroll control; the inspector's six
  tabs wrap to two rows instead. A tab's count takes the rail's pill at the tighter inline
  inset a strip has room for: 1px block, 4px inline.
- **Skip link:** first in the tab order, `raised` fill with a `strong` hairline, off-canvas
  until focused.

### Menus, Popovers, Dialogs, Toasts
- **Menu:** `raised` at 4px padding, `default` hairline, 8px corners, 12rem to 22rem wide.
  Items are 36px rows at 8px 12px with 6px corners; hover is `selected` fill; group labels
  are the `label` role; hints are mono muted.
- **Combobox / listbox:** a `raised` panel under the text box at 4px padding, `default`
  hairline, 8px corners, 18rem tall at most. Options are 36px rows at 8px 12px with 6px
  corners; the active one — where the keyboard is, since focus stays in the text box — takes
  the `selected` fill and nothing else, and the chosen one carries the registry's `check` at
  14px in secondary ink at the end of the row.
- **Dialog:** centred on the scrim at 24px padding, `raised` fill, `default` hairline, 8px
  corners, `h4` title, secondary-ink body, right-aligned footer at 12px gap. Sizes 24rem,
  34rem, 52rem. Used only where inline confirmation cannot work.
- **Toast:** a 26rem `raised` card at 12px 16px with 8px corners, top-placed below the
  shell bar and the page header so it never covers a control that opened it; full width
  below 768px. The tone tints the whole hairline and the icon, and is written as the first
  words of the title. Only writes carry the success tone.

### States
- **Skeleton:** `subtle` fill pulsing between 1 and 0.55 opacity over 1.6s; text bars are
  12px pills, blocks are 64px at 8px corners, circles 40px. Loading keeps the page frame and
  mirrors the geometry of the rows or cards that are coming.
- **Notice:** `pane` fill, 1px `default` hairline tinted by tone, 4px corners, icon in tone
  ink beside a `body-sm` title at 600 and the sentence that states the problem.

### Signature: the reading surface
`paper` is a `Card` variant and a `.rh-surface-paper` utility: near-white in both themes
with `paper-ink` text, `paper-line` edges and three multiplied marks (SyncTeX target in the
accent tint, accepted anchor in green, search hit in warning yellow), each edged at full
strength. Quoted source text is serif at `lead` size behind a 2px start rule and is never
clipped or capped to the prose measure.

## Do's and Don'ts

### Do:
- **Do** address every colour by semantic token (`--rh-surface-*`, `--rh-text-*`,
  `--rh-status-*`, `--rh-feedback-*`, `--rh-accent*`); the lint fails on a literal outside
  `palette.css` and the theme files.
- **Do** render every scientific status as glyph, label and tint together, from
  `STATUS_META`, so it survives greyscale and a projector.
- **Do** keep the accent for model activity and the primary send/run action, and write the
  reason a thing is accent-coloured in words beside it.
- **Do** draw depth as a 1px hairline plus a surface step; reserve `--rh-shadow-overlay`
  for a drawer over a scrim.
- **Do** keep reading text at or above 12px at every density, and every pointer target at or
  above 24px; use `max()` against the floor when density scales a size.
- **Do** keep the page frame (`h1`, description, toolbar) in every state, load with
  skeletons that mirror the coming geometry, and make every empty state name a next action.
- **Do** apply `paper` together with its ink (`.rh-surface-paper` or `<Card surface="paper">`),
  and draw marks on it with `mix-blend-mode: multiply` in the paper tints.
- **Do** query the container, not the viewport, inside a page or an inspector; only the
  shell reads the window.
- **Do** underline links (`text-decoration-color: --rh-border-strong`, current colour on
  hover) and confirm inline wherever inline works.
- **Do** honour reduced motion through the tokens: durations collapse to 1ms and the hover
  and press scales become 1.

### Don't:
- **Don't** use the accent as an emphasis, hover, link, navigation or decoration colour, or
  on anything that states scientific truth.
- **Don't** put a scientific status colour on anything that is not a scientific state, or a
  feedback tone on anything that is.
- **Don't** draw a coloured side border, stripe or tab thicker than 1px on a card, row or
  notice; 2px belongs only to the selected tab marker and the quotation rule.
- **Don't** set a kicker or eyebrow: no 11px uppercase word before a sentence or above a
  heading. The `label` role names groups, columns and definition terms only.
- **Don't** use gradient text, a gradient fill, or any transparency other than the scrim.
- **Don't** use an emoji or a text glyph as an icon; icons come from the bundled registry
  behind `Icon`, never inline.
- **Don't** open a modal where an inline confirmation works, and never fake an undo for a
  write that has none.
- **Don't** show a spinner where a skeleton can hold the frame, or replace the page frame
  with a state.
- **Don't** use a cool grey, a bare pixel gap outside the 4px scale, a fluid `clamp()`
  size, a numeric border width, or a third motion duration.
- **Don't** fetch anything at runtime: no remote `@import`, `url()`, font or icon.
- **Green is the accepted state's.** A badge that reports a machine's result — included by screening, verified, supported, a valid anchor, or the absence of a verdict — is neutral, told apart by its glyph; only a persisted human acceptance wears the accepted family. Feedback tones are not separate hues, so this is one rule on a badge, not two.
