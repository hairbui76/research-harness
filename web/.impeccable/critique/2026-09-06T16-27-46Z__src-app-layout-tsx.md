---
target: "web cockpit: app shell, conversation workspace, research pages"
total_score: 20
max_score: 40
na_heuristics: 
p0_count: 1
p1_count: 3
target_identity: "file:/mnt/virtual/repo/research-harness/.claude/worktrees/cli-providers/web/src/app/Layout.tsx"
target_fingerprint: "sha256:ef09eb9a68f5a2be97c81bf0594919ba0d858238e3d1452fda250740acc1aa4a"
target_path: /mnt/virtual/repo/research-harness/.claude/worktrees/cli-providers/web/src/app/Layout.tsx
timestamp: 2026-09-06T16-27-46Z
slug: src-app-layout-tsx
---
**Method:** dual-agent (A: design review, isolated; B: deterministic evidence, isolated). No browser automation in this environment and no Playwright/Puppeteer in the repo, so every browser-overlay step was skipped and measured evidence from tokens, CSS, components and tests was substituted. No user-visible overlay exists. The user's screenshots were not on disk; both agents worked from source.

## Design Health Score

| # | Heuristic | Score | Key issue |
|---|-----------|-------|-----------|
| 1 | Visibility of System Status | 3 | States exist everywhere but replace the page frame; InspectorPane has no error branch; offline never implemented; Skeleton unused in web/src |
| 2 | Match System / Real World | 2 | Raw snake_case enums in Claims.tsx; "4718592 bytes" while formatBytes ships unused; internal doc citations in UI copy |
| 3 | User Control and Freedom | 2 | No undo; one-click Accept writes accepted state; one-click provider Remove; Settings tab switch discards input |
| 4 | Consistency and Standards | 2 | h1 at 13px vs 28px; h4 smaller than body; one border-width token, three widths shipped |
| 5 | Error Prevention | 2 | Irreversible action has least ceremony; danger colour on the reversible one |
| 6 | Recognition Rather Than Recall | 2 | Six status descriptions authored and never rendered; evidence ids typed from memory |
| 7 | Flexibility and Efficiency | 1 | Zero shortcuts, no palette, no batch accept, no search/filter/sort |
| 8 | Aesthetic and Minimalist Design | 2 | 182-232 character lines; eight notice strips; eight controls per message |
| 9 | Error Recovery | 3 | Excellent vocabulary; research pages collapse refusals; inspector lacks an error branch |
| 10 | Help and Documentation | 1 | No help affordance; empty states teach nothing |
| **Total** | | **20/40** | **Acceptable - significant improvements needed** |

## Design specificity

The design system is authored; the application is not. One warm ramp with cool greys declared a bug, a paper surface with its own ink tokens that survives dark mode, an accent gated by CI from resembling any scientific status, and a component that refuses to reuse ConflictNotice because a provider disagreement has no accepted side. Nine of eleven pages do not carry it: Corpus, Claims, Taxonomy and Stale are card-wrapped tables and Overview leads with a stat-tile row on the page whose brief forbids vanity metrics.

Deterministic scan: detector returned [] over web/src (139 files, exit 0) and 2 findings over design/src (332 files, exit 2), both rule `side-tab`: Toast.css:42 and ErrorNotice.css:9. ErrorNotice is imported by conversation and research components. No .impeccable config and no disable comments exist, so the clean result is unsuppressed, but web/src holds only eight CSS files and the detector matches regex on non-HTML files, so computed contrast, geometry, focus order and overflow are out of its reach.

## Priority issues

**[P0] PDF evidence highlights unreadable in the default theme.** web/src/pdf/pdf.css:56-68 fills search hits and accepted anchors with dark-canvas tints under mix-blend-mode: multiply over the paper surface; in dark the page ink under the highlight computes to 1.13:1 and 1.12:1. Light is correct. Fix: paper-specific highlight tints that stay light in both themes, as --rh-text-on-paper already does for ink. Command: /impeccable audit

**[P1] Accept has no ceremony and danger is on the wrong button.** ReviewActions.tsx:96-99 writes accepted scientific state on one unconfirmed click while reject carries variant danger and demands a typed sentence. Fix: confirm the accept with a restatement of what will be written; move danger off reject; add undo to the toast. Command: /impeccable harden

**[P1] Review costs one page load per candidate.** No multi-select, batch accept, decide-and-next, search, filter, sort, or keyboard shortcuts anywhere. Fix: policy-gated batch accept on the routine tier, decide-and-next, and a shortcut layer with a command palette. Command: /impeccable shape

**[P1] Loading, empty and error destroy the page frame.** All ten research pages return the state before FullPageWorkspace, which renders the title, header, toolbar and footer, so those states have no heading at all; empty copy teaches nothing. Fix: keep the frame mounted, use the shipped Skeleton, give every empty state a next action. Command: /impeccable clarify

**[P2] The layout does not check whether its own content fits.** One measure cap exists cockpit-wide; at 1920px the transcript runs about 182 characters and research prose about 232. Six inspector tabs measure about 734px inside a 352px pane with no overflow affordance, putting Conflicts and Stale off-screen. Fix: cap prose near 72ch, tables stay wide; vertical inspector tabs. Command: /impeccable layout

## Persona red flags

Alex (power user): no shortcuts, palette, batch or search; Promote is an unlabeled icon. Sam (assistive technology): assertive role=alert on every promote dialog and on every page while read-only; six decision meanings live in unreachable title attributes; skip link and focus outlines are good. Riley (stress tester): Settings tab switch loses a typed entry; provider Remove has no confirmation while forgetting a project does; 300 works render unvirtualised.

## Minor observations

12px is the dominant body size and research tables render at 11.15px because Feedback.tsx:98 forces compact density. Two of thirty-one web test files run axe, and the harness disables contrast, landmark and heading-one rules. Three layout media queries in web/src, none in design/src, no container queries; narrow layout is untested. --rh-space-0, --rh-motion-slow and --rh-text-on-accent are dead. Icon buttons fall to 22x22px in compact density, below the 24px floor.

## Questions to consider

Should the rail's eleven destinations become three groups? Why does Accept ask for nothing when Reject asks for a sentence? Where is a researcher meant to learn Qualified versus Contested, given the six authored descriptions are never rendered? After the one-time egress disclosure, what tells you on message forty where your unpublished work is going?
