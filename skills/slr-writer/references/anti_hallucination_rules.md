# Anti-Hallucination Rules (enforced by every writing agent)

The fastest way to destroy a survey's credibility is a fabricated citation or an unsupported number. These rules are non-negotiable.

## The five gates

1. **Citation existence.** `\cite{k}` is allowed only if `k` exists in `papers.json` / `refs.bib`. If you feel a citation is needed but no corpus paper fits → write `[NEEDS SOURCE]` inline and surface it to the user; never invent an author/title/year.

2. **Claim → card.** Every sentence that states a fact, result, or number must be backed by a line in some `05_evidence_cards/*.md`. Before writing a numeric claim, confirm the exact value is on a card. No card → no number.

3. **Numbers verbatim.** Copy values and units exactly as the card records them (which copied them from the PDF). Do not convert, round, average, or "estimate". If the card says `not reported`, the prose says so or omits the metric.

4. **Claimed vs verified.** Use language that marks epistemic status:
   - verified (from a results table): "reduces memory by $3.2\times$~\cite{12}".
   - author claim (from abstract/intro): "the authors argue that ...~\cite{12}".
   - Never present an author's aspiration as a measured result.

5. **Abstract-only papers.** A paper with `pdf_available: false` / `citation-safe numbers: no` may be cited for its *existence/direction* only ("several works explore ternary NIDS~\cite{...}"), never for a specific number.

## Positioning, not dunking

State competitors' limitations factually to motivate the survey's gap (CLAUDE.md: "AVOID over-critical takes on competitor weaknesses"). "Method X does not evaluate cross-dataset drift" — yes. "Method X is fundamentally flawed" — no.

## Self-check before finishing a section

- [ ] Every `\cite` key is in refs.bib.
- [ ] Every number appears on a cited card with the same unit.
- [ ] No `[NEEDS SOURCE]` left unsurfaced.
- [ ] Claimed vs verified language is correct.
- [ ] No specific number attributed to an abstract-only paper.

The `assembler_checker_agent` re-verifies gates 1–2 mechanically in Phase 5 and reports any `UNVERIFIED` sentence.
