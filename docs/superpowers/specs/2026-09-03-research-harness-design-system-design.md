# Research Harness Design System — Design Specification

**Status:** Design approved in conversation; awaiting review of this written specification.

**Scope:** Product and architecture design only. This document does not authorise component migration or production implementation.

## 1. Goal

Turn the useful visual foundations in the local `design/` bundle into a first-class Research Harness Design System shared by every Web research surface. The result should provide the focused density and conversation ergonomics of a modern model harness while retaining an editorial, source-reading character suitable for scientific work.

The Design System owns presentation contracts. It does not own research state, application capabilities, model calls, or accepted-state mutation.

## 2. Assessment of the source bundle

The current bundle provides a coherent warm-neutral palette, typography, spacing, radius, motion, fifteen primitives, guideline specimens, and a useful three-pane app composition. These are strong inputs for Research Harness.

It is not production-ready as-is:

- branding and content are specific to the placeholder customer-support product `Warmline` and its agent `Fin`;
- components are JavaScript prototypes dominated by inline styles, while the Web client uses strict TypeScript;
- fonts and icons are loaded from public CDNs, conflicting with local-first/offline and egress expectations;
- the component set does not cover scientific authority, provenance, graph references, attachments, or manuscript work;
- Dialog, Tabs, Tooltip, and Icon behaviours do not yet meet the intended accessibility contract;
- the existing button scale motion is too strong for a dense research interface;
- no dark theme is defined.

Therefore the source bundle is a design input, not a runtime dependency or code to copy unchanged.

## 3. Package architecture

`design/` becomes a production package in the existing pnpm workspace:

```text
design/
├── package.json
├── src/
│   ├── tokens/
│   │   ├── palette.css
│   │   ├── semantic.css
│   │   ├── typography.css
│   │   ├── spacing.css
│   │   ├── radius.css
│   │   └── motion.css
│   ├── themes/
│   │   ├── dark.css
│   │   └── light.css
│   ├── primitives/
│   ├── research/
│   ├── conversation/
│   ├── manuscript/
│   ├── workspace/
│   └── index.ts
├── specimens/
├── tests/
└── README.md
```

The package emits ESM, CSS, and TypeScript declarations. React is a peer dependency. The Web client consumes the package through the local workspace rather than duplicating primitives or importing prototype files.

Dependency direction is one-way:

```text
tokens and themes
       ↓
presentation primitives
       ↓
research/conversation/manuscript/workspace components
       ↓
Web application screens
```

Application state supplies typed view models and callbacks. Design components never call the daemon, write canonical files, alter authority, or invoke model providers directly.

## 4. Themes and visual language

The product ships with both themes:

- **Dark is the default:** warm near-black canvas, slightly lighter working panes, restrained borders, and a neutral paper surface for PDF/manuscript reading.
- **Light is optional:** warm cream canvas and white working panes derived from the existing foundation.

Both themes use identical semantic token names and switch through a root `data-theme` attribute. The preference is stored locally and does not affect scientific state.

The placeholder `Fin Orange` becomes a Research Harness AI/action accent. It is limited to model activity, the primary send/run action, active focus/reference tracking, and selected AI provenance. It is not decorative and does not encode scientific truth.

Scientific states have separate semantic tokens and visible labels/icons:

- `accepted`;
- `candidate`;
- `qualified`;
- `contested`;
- `stale`;
- `private`.

No status is communicated by colour alone. All theme/status combinations must meet WCAG 2.2 AA contrast for their intended text and control sizes.

Typography has three roles: sans for UI/conversation, serif for editorial source/manuscript moments, and mono for IDs, provenance, code/equation metadata, and machine diagnostics. Runtime assets are local: no font, icon, stylesheet, or component is fetched from a CDN. Until appropriately licensed fonts are self-hosted, system font stacks are the correct fallback.

The system supports `comfortable` density for conversation/manuscript and `compact` density for corpus tables, graph results, and review queues. Motion is restrained—approximately `1.02` hover and `0.98` press where scale is appropriate—and respects `prefers-reduced-motion`.

## 5. Component boundaries

### 5.1 Primitives

Primitives know nothing about research semantics:

- Button, IconButton, Icon, Badge, Tag, Card;
- Input, Textarea, Select, Checkbox, Radio, Switch;
- Tabs, Tooltip, Dialog, Toast;
- Popover, Menu, Combobox, Progress, Skeleton;
- ScrollArea, ResizablePane, VirtualList.

### 5.2 Research semantics

- `EntityRef` resolves and opens stable `@` references;
- `AuthorityBadge` presents accepted/candidate/qualified/contested/stale/private state;
- `SourceAnchor` presents exact page/block/table/span targets;
- `EvidenceCard` and `ClaimCard` present typed research objects;
- `ProvenancePath` presents Claim → Evidence → Artifact navigation;
- `ContextReceipt` presents what a model call did and did not receive;
- `ReviewDecisionBar`, `ConflictNotice`, and `SaveToCorpusAction` expose existing application actions without implementing their rules.

### 5.3 Conversation

- Message and MessageContent;
- Composer and ReferencePicker;
- AttachmentTray, ImageAttachment, and PdfAttachment;
- ModelSelector and SessionList.

Markdown/KaTeX, attachment processing, model compatibility, and context assembly remain Web/application integrations behind these presentation components.

### 5.4 Manuscript

- FileTree and SourceEditorFrame;
- PdfPreview;
- CompilerStatus and CompilerDiagnostic;
- AuditFinding and CandidateDiff.

The Design System provides frames and visual contracts. Editor engines, PDF.js, KaTeX, compiler invocation, and SyncTeX are application adapters rather than primitive dependencies.

### 5.5 Workspace composition

- AppShell and ProjectRail;
- ConversationWorkspace and ResearchInspector;
- FullPageWorkspace;
- ManuscriptWorkspace.

Pages compose these components and must not recreate buttons, dialogs, badges, theme values, or state styles locally.

## 6. Accessibility contract

WCAG 2.2 AA is the baseline, including:

- visible, consistent focus treatment in both themes;
- Dialog focus trap, Escape close when allowed, accessible labelling, and focus restoration;
- Tabs arrow-key navigation and roving tabindex;
- keyboard operation for composer, attachment tray, inspector, menus, references, and resizable panes;
- decorative icons hidden from assistive technology and meaningful icons explicitly labelled;
- no information available only on hover or only through colour;
- stable focus after send, pane collapse, error recovery, and navigation;
- reduced-motion support;
- textual alternatives for mathematical, PDF, graph, and compiler states where appropriate.

## 7. Error and async-state language

The system provides consistent presentation for loading, empty, partial, stale, blocked, retryable, and fatal states. Named research cases include:

- offline or provider unavailable;
- attachment unsupported or omitted;
- privacy/egress blocked;
- graph/index rebuilding;
- source anchor stale;
- LaTeX compilation failure;
- insufficient permission/read-only host;
- partial or interrupted streaming response.

An error component never owns recovery logic. It receives a typed state and optional actions. Presentation must preserve successful prior content and make clear whether the researcher's draft or source is safe.

## 8. Governance and verification

Every production component requires:

- a typed public API and no hidden daemon dependency;
- examples for default, hover, focus, disabled, loading, empty, and error states as applicable;
- unit tests for interaction and controlled/uncontrolled behaviour;
- keyboard and automated accessibility tests;
- visual regression coverage for dark/light and compact/comfortable variants;
- contrast verification for semantic states;
- documentation of any content, layout, or accessibility constraint.

Linting should prevent raw palette use outside token/theme files and discourage reimplementation of primitives inside the Web client. Heavy integrations receive contract tests at the Web adapter boundary rather than becoming Design System dependencies.

## 9. Migration and cleanup

Migration is incremental so existing research screens remain usable:

1. establish package/build, semantic tokens, and dark/light theme switching;
2. replace the common primitives with strict TypeScript implementations;
3. build AppShell, ProjectRail, pane, and responsive foundations;
4. build research semantic components;
5. build conversation, attachment, and ContextReceipt components;
6. build manuscript workspace components;
7. migrate existing Web routes one surface at a time;
8. verify behaviour, accessibility, and visual parity before deleting replaced CSS/components;
9. remove all obsolete placeholder/generator assets.

Retain and translate the warm-neutral foundation, typography roles, spacing/radius discipline, semantic-token idea, useful component inventory, and three-pane composition.

Rewrite prototype JSX as TypeScript and tokenised styles; replace incomplete accessibility and motion behaviours; replace placeholder branding/content; and add Research Harness-specific components.

After production replacements pass their gates, remove the marketing kit, landing template, Warmline login/reports/settings examples, helpdesk data, `Fin`/`Warmline` naming, CDN icon/font paths, generated bundle/bootstrap/thumbnail/manifest artifacts, and handwritten declaration files. Do not keep a permanent legacy tree without a demonstrated testing or documentation purpose.

## 10. Relationship to the product architecture

- `deepseek-harness/` remains an interaction-density and layout reference only.
- ResearchGraph provides references/data; Design System only presents them.
- Conversation and attachment services own lifecycle; components present states/actions.
- The LaTeX service owns compilation; manuscript components present source, PDF, mapping, and diagnostics.
- The Research Core and capability layer remain the only authority for accepted-state mutation.

## 11. Non-goals

- Reproducing the Warmline customer-support product.
- Copying DeepSeek Harness implementation or introducing a runtime dependency on it.
- Building a generic public component library for unrelated products.
- Moving domain rules or API calls into UI components.
- Shipping a third theme, branding editor, or plugin theming API before a measured need.
- Keeping obsolete generator files merely because they existed in the source bundle.

## 12. Acceptance criteria

1. The Web client consumes one local Design System package with no duplicated primitive/theme source of truth.
2. Dark is the default, light is selectable, and the same semantic states remain legible and accessible in both.
3. A conversation workspace, full research page, and manuscript workspace compose the shared package without embedding domain mutation rules.
4. Runtime rendering performs no CDN request for fonts, icons, styles, or Design System code.
5. Dialogs, tabs, menus, composer actions, inspector navigation, and resizable panes meet the keyboard/accessibility contract.
6. Candidate, accepted, qualified, contested, stale, and private states are distinguishable without colour.
7. Web pages do not recreate shared primitives or use raw palette values outside an approved visualisation case.
8. Existing Web behaviour remains covered while routes migrate incrementally.
9. Obsolete Warmline/Fin/helpdesk/marketing/generator artifacts are removed only after their useful foundations have production replacements.
