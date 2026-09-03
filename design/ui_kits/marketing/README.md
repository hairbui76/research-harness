# UI kit — Marketing site

Click-through recreation of the brand's public site language: warm-cream canvas, white
banded sections, 80px Saans-scale headlines with -2.4px tracking, sharp 4px buttons and
Fin Orange reserved for AI moments.

| File | Surface |
| --- | --- |
| `index.html` | Mount + router. Nav links switch screens (Blog → article, Solutions/Docs → pricing). |
| `Chrome.jsx` | `Wordmark`, `Eyebrow` (mono label), `Nav`, `LogoStrip`, `CtaBand`, `Footer`. |
| `HomeScreen.jsx` | Hero + live-chat panel, trust strip, metric band, feature grid, editorial quote + report-palette metric cards. |
| `ProductScreen.jsx` | Fin product page: split hero with tabbed demo (Answers / Actions / Handover), numbered capability grid. |
| `PricingScreen.jsx` | Term `Switch`, three plans, comparison table, FAQ set in Serrif. |
| `ArticleScreen.jsx` | Editorial post: mono metadata, serif body at 20/1.5, accent-rule pull quote, subscribe band. |

Composes the published primitives only (`Button`, `IconButton`, `Card`, `Badge`, `Tag`,
`Icon`, `Input`, `Switch`, `Tabs`) from `_ds_bundle.js` — no primitives are re-implemented
here. Screens are plain browser JSX (globals, no ESM) so the page runs from `file://`.

**Provenance:** no source repo, Figma file or screenshots were supplied. Copy, company
names and data are invented placeholders; the layout language follows the written brief in
`readme.md`, not a recreation of any specific vendor's page.
