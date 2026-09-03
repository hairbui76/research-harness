# Warmline Design System

A warm-neutral, editorially-typeset design system for an AI-first customer service
platform: a shared inbox, an AI agent ("Fin") that answers before a human does, reporting,
and the marketing site that sells all of it.

**Brand name caveat.** The brief that produced this system described a real vendor's public
site but supplied no logo, no wordmark, no product code and no images. Nothing here
reproduces that vendor's mark or proprietary UI. The system ships under the neutral
placeholder name **Warmline** (AI agent: **Fin**, the one name the brief defined as a token
concept, `--color-fin`). Search-and-replace "Warmline" when the real identity arrives.

---

## 1. Sources

| Source | Status |
| --- | --- |
| Written brand brief ("Design System Inspired by Intercom", pasted in chat) | **Used** — every colour, type row, radius, spacing step and interaction value below comes from it verbatim. |
| Codebase / repo | Not provided. |
| Figma file or link | Not provided. |
| Screenshots, slide decks, PDFs | Not provided. |
| Font binaries (Saans, Serrif, SaansMono, MediumLL/LLMedium) | **Not provided — substituted.** See §6. |
| Logos, illustrations, photography, icon set | **Not provided — none invented.** See §7. |

Because there is no code or Figma source, the component inventory is the standard set for
this brand's needs (§8), and the UI kits (§9) are original compositions in the brief's
visual language — not recreations of anyone's screens.

---

## 2. Products represented

1. **Marketing site** — warm-cream canvas, white banded sections, 80px headlines, editorial
   long-form. Surfaces: home, AI-agent product page, pricing, blog article.
2. **Helpdesk app** — dark icon rail, white working panes, three-pane inbox, reporting,
   settings. Surfaces: sign-in, inbox, reports, settings.

---

## 3. Content fundamentals

**Voice: plain, short, confident, slightly dry.** Sentences are declarative and land on a
verb. No exclamation marks, no hype adjectives, no "revolutionary".

- **Person.** "You" for the reader; "we" only in customer quotes and company voice. The
  product is named, not personified: "Fin resolves it", not "Fin will happily help!".
- **Headline grammar.** A claim with a twist, 3–7 words, sentence case, full stop included:
  "Support that answers before you do." · "Pay per seat. Pay per resolution." · "The agent
  that resolves, not deflects." Never Title Case, never a colon-subtitle construction.
- **Subheads** explain the mechanism in one sentence, ≤ 18 words: "Fin resolves the
  questions your team keeps repeating. Your people take the ones that matter."
- **Body** is specific and numeric where it can be: "65% resolved instantly", "1.2s median
  first reply", "$49.00 on 4 Sept" — never "lightning fast".
- **UI labels** are one or two words, sentence case: "Start free trial", "Draft with Fin",
  "Reset defaults", "Public reply". Buttons name the outcome, not the mechanism.
- **Mono labels** are the metadata layer — uppercase, wide-tracked, terse:
  `RESOLUTION RATE`, `AI-FIRST CUSTOMER SERVICE`, `SOURCE: SECURITY/SSO-SETUP`.
- **Empty and error states** stay light but never cute: "Nothing here. Nice." · "Enter your
  password to continue."
- **Editorial (blog) voice** loosens: first-person plural research findings, longer serif
  paragraphs, an argumentative pull quote — "Measure resolution, or measure nothing."
- **Numbers.** Percentages whole ("65%"), deltas signed ("+4.1pt", "-0.3s"), money with
  cents when it's a transaction ("$49.00"), abbreviated when it's scale ("25,000+ teams").
- **No emoji anywhere** — not in UI, not in marketing, not in docs. The `smile` composer
  icon is an affordance for the customer's emoji, not the brand's.
- **Punctuation.** Em dashes for asides, `·` as a separator in metadata rows, en dash in
  ranges ("3–5 business days"). Ampersands only inside topic names.

---

## 4. Visual foundations

**Canvas.** Warm off-white `#faf9f6` (`--surface-page`) is the default page. White
`#ffffff` (`--surface-primary`) is the *working* surface — app panes and the banded
sections that break up a long marketing page. Off-black `#111111` is ink, and also the
inverse surface for CTA bands, the app rail and outgoing message bubbles. Two background
colours per page, maximum: cream and white, with one inverse band for punctuation.

**Type.** One geometric sans does nearly everything, with 1.00 line-height and negative
tracking on every heading: 80/-2.4, 54/-1.6, 40/-1.2, 32/-0.96, 24/-0.48. That combination
is the identity — headlines read as compressed, engineered slabs of text. Body is 16/1.50
with normal tracking; 14/1.40 at weight 300 for secondary copy. A low-contrast serif
carries editorial moments (pull quotes, FAQ answers, article body at 20/1.5/-0.16). Mono at
12px, 0.6–1.2px tracking, uppercase, is *only* labels and metadata — never body copy.

**Colour discipline.** Fin Orange `#ff5600` marks the AI agent and nothing else: the Fin
pip, the "AI" badge, the accent button, the source citation, the Fin series in a chart.
It is never a decorative wash, never a gradient, never a hover colour. The report palette
(blue `#65b5ff`, green `#0bdf50`, lime `#b3e01c`, pink `#ff2067`, orange `#fe4c02`, red
`#c41c1c`) appears in data visualisation only, as a 4px rule under a metric or a bar in a
chart. Neutrals are warm all the way down (`#313130` → `#7b7b78` → `#dedbd6` → `#d3cec6`);
cool greys are a bug. Translucency uses oklab inks (`--ink-10`…`--ink-60`) rather than
rgba, so tints stay warm.

**Geometry.** 4px radius on buttons, tags and small controls; 6px on nav items; 8px on
cards and containers. Nothing is pill-shaped except avatars and status pips (999px). The
sharpness is deliberate: near-rectangular interactive elements against soft warm surfaces.

**Depth.** No shadows. Elevation is expressed as a 1px oat hairline `#dedbd6` plus a
surface change (cream card on white, white card on cream). Overlays are the only exception:
a dialog sits on an `--ink-30` scrim and takes a single soft shadow token so it reads above
the page. Dividers are 1px oat; a 2px off-black left border marks the selected row.

**Motion and states.** Fast and physical. Buttons scale to 1.1 on hover with a colour
inversion (dark → white, white → dark) and snap to 0.85 with a deep green fill on press;
transitions are ~120–160ms with a linear/`ease-out` feel. Cards darken their border on
hover rather than lifting. No bounces, no parallax, no entrance animations on scroll, no
looping ambient motion — the page is still until touched.

**Layout.** 1200px content column with 40px gutters on marketing; full-viewport panes in
the app (64px rail, 320px list, fluid thread, 296px details). Sticky elements: the
marketing nav and the app panel headers. Spacing steps: 8, 10, 12, 14, 16, 20, 24, 32, 40,
48, 60, 64, 80, 96. Section rhythm alternates cream → white band → cream → inverse band.
Breakpoints: 425, 530, 600, 640, 768, 896.

**Transparency and blur.** Almost none. Translucent ink is used for hairlines and hover
tints; blur is not part of the language — no frosted panels, no protection gradients over
imagery. Where an overlay needs separation it uses the flat `--ink-30` scrim.

**Imagery.** None supplied, and none invented. When real photography arrives it should
follow the surface temperature — warm, daylight, low saturation, no cool blue casts, no
grain filters. Product screenshots belong on white with a 1px oat border and 8px radius.
Illustration, if introduced, should be flat and warm; there is no evidence in the brief for
hand-drawn or textured backgrounds, and nothing here fakes them.

---

## 5. Tokens

`styles.css` (root) is nothing but `@import` lines; consumers link that one file.

| File | Contains |
| --- | --- |
| `tokens/fonts.css` | Font-family tokens + the Google Fonts substitution import (§6). |
| `tokens/colors.css` | Primary, report palette, warm neutral scale, oklab inks. |
| `tokens/typography.css` | One size/line-height/tracking/weight trio per role. |
| `tokens/spacing.css` | The 8→96 step scale. |
| `tokens/radius.css` | `--radius-button` 4px, `--radius-nav` 6px, `--radius-card` 8px. |
| `tokens/motion.css` | Durations, easings, `--hover-scale` 1.1, `--active-scale` 0.85. |
| `tokens/semantic.css` | Aliases components consume: `--text-*`, `--surface-*`, `--border-*`, `--button-*`, `--feedback-*`. |
| `tokens/base.css` | Body reset, link colours, focus ring, selection. |

Components reference semantic tokens only; raw palette tokens are for tokens files, cards
and data visualisation.

---

## 6. Fonts — substituted, please replace

The brief names **Saans**, **Serrif**, **SaansMono** and **MediumLL/LLMedium**. None are
publicly licensed and no binaries were supplied, so `tokens/fonts.css` loads the nearest
Google Fonts equivalents and keeps the real names in the fallback stack:

| Brief | Substitute | Why |
| --- | --- | --- |
| Saans | **Schibsted Grotesk** | Geometric grotesque, tight apertures, holds up at -2.4px tracking. |
| Serrif | **Newsreader** | Low-contrast editorial serif with a light weight. |
| SaansMono | **JetBrains Mono** | Neutral mono, legible at 12px uppercase with wide tracking. |
| LLMedium | **Schibsted Grotesk 700** | Same family at the bold weight the brief describes. |

**Ask:** send the real font files (woff2) and I will swap the `@import` for `@font-face`
rules — no token or component changes needed.

---

## 7. Iconography

- **No icon assets were supplied** — no icon font, no sprite, no SVG set, no logo, no
  illustrations. Nothing was drawn or reconstructed from memory.
- **Substitution: [Lucide](https://lucide.dev) v0.544.0, loaded from CDN** as individual
  SVGs used as CSS masks, so a single `color` prop tints them. Lucide's 2px stroke,
  rounded caps and 24px grid are the closest available match to the brief's sharp,
  utilitarian tone. **Flagged for replacement** if a house set exists.
- **Wrapper:** `Icon` (`components/core/Icon.jsx`) takes a Lucide `name`, `size` and
  `color`. `IconButton` wraps it for square 32/40/48px targets. Never inline a raw `<svg>`
  in product code — go through `Icon` so sizing and colour stay tokenised.
- **Sizes in use:** 14px inline with 14px text, 16px in buttons, 18–20px in nav and panel
  headers, 24px as a feature-card mark.
- **Where the brand mark goes:** the wordmark is rendered as plain type in the sans face
  (see `guidelines/logotype.card.html`), and the app rail uses a 32px Fin-Orange square
  holding the letter "W". Both are placeholders for a real mark.
- **Emoji are not used** as iconography, and unicode glyphs appear only as typographic
  punctuation (`·`, `—`, `→`, `⌘↵` in the composer hint).
- `assets/` is intentionally empty; there was nothing licensed to copy in.

---

## 8. Components

Fifteen primitives, grouped by concern. Each directory has `<Name>.jsx`, `<Name>.d.ts`,
`<Name>.prompt.md`, and one `@dsCard` HTML showing states side by side.

**`components/core/`** — `Button`, `IconButton`, `Icon`, `Card`, `Badge`, `Tag`
**`components/forms/`** — `Input`, `Select`, `Checkbox`, `Radio`, `Switch`
**`components/feedback/`** — `Dialog`, `Toast`, `Tooltip`
**`components/navigation/`** — `Tabs`

Alphabetically: `Badge`, `Button`, `Card`, `Checkbox`, `Dialog`, `Icon`, `IconButton`,
`Input`, `Radio`, `Select`, `Switch`, `Tabs`, `Tag`, `Toast`, `Tooltip`.

**Intentional additions.** No source defined an inventory, so this is the standard set for
a helpdesk + marketing pair. Two entries deserve a note: `Icon` exists because the icon set
is a CDN substitution and needs one choke point; `Tag` and `Badge` are kept separate
because tags are removable/selectable filters while badges are read-only status.

---

## 9. UI kits

| Kit | Entry | Screens |
| --- | --- | --- |
| Marketing site | `ui_kits/marketing/index.html` | Home, Fin product page, Pricing, Blog article |
| Helpdesk app | `ui_kits/app/index.html` | Sign-in, Inbox (three panes + composer + Fin draft), Reports, Settings |

Both are click-through: the marketing nav switches screens, and the app starts at sign-in,
then the rail moves between inbox, reports and settings. Every kit composes the published
primitives from the generated bundle — no primitive is re-implemented inside a kit. Each
kit folder has its own README with a file-by-file map.

---

## 10. Index

```
readme.md              this file
SKILL.md               portable skill wrapper (Claude Code / Agent Skills)
styles.css             @import manifest — the only file consumers link
thumbnail.html         homepage tile
tokens/                fonts, colors, typography, spacing, radius, motion, semantic, base
guidelines/            17 foundation specimen cards (Colors, Type, Spacing, Brand)
components/            core · forms · feedback · navigation (15 primitives)
templates/landing-page/ Landing page starting template (Design Component)
ui_kits/ds-boot.js     kit bootstrap — namespace globals + source fallback
ui_kits/marketing/     home, product, pricing, article + chrome
ui_kits/app/           sign-in, inbox, reports, settings + rail
assets/                empty — no licensed assets were supplied
```

Foundation cards, component cards and both kit entries all register in the Design System
tab: groups **Colors**, **Type**, **Spacing**, **Brand**, **Components**, **Marketing
site**, **Helpdesk app**. `templates/landing-page/LandingPage.dc.html` is the one
starting template consuming projects can copy — hero, trust strip, feature trio and
inverse CTA band, with the chat panel and trust strip as toggles.

---

## 11. Open questions

1. Real font files for Saans / Serrif / SaansMono, and the actual role of MediumLL vs
   LLMedium (the brief lists both; they are aliased to one substitute here).
2. The real wordmark, favicon and any product imagery.
3. Whether a house icon set exists — if so, Lucide comes out.
4. The real brand name, to replace "Warmline" throughout.
5. Confirmation of the press-state green `#2c6415` (the brief specifies it for active
   buttons; it is the one colour in the system that appears nowhere else).
