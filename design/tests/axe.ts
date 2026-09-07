import axe from 'axe-core';

/**
 * Shared axe-core harness for the Design System tests.
 *
 * Two rules are off, for two different reasons:
 *
 * * `color-contrast` — jsdom applies no stylesheet and paints nothing, so the rule has no
 *   colours to compare. `scripts/check-contrast.mjs` gates every token pair the system
 *   declares, and the cockpit's browser suite runs axe's own rule on every route in both
 *   themes.
 * * `region` — a component is rendered here without a page around it, so its content
 *   belongs to no landmark through no fault of its own. The rule runs route-wide in the
 *   browser suite.
 *
 * The page-level rules this list used to also hold (`bypass`, `document-title`,
 * `html-has-lang`, `landmark-one-main`, `page-has-heading-one`) are on: they match the root
 * `html` element, which a fragment context never includes, so they suppressed nothing.
 * `heading-order` and the `landmark-*` rules do run against a fragment, and are on.
 */
const DEFAULT_DISABLED_RULES = ['color-contrast', 'region'];

export interface AxeCheckOptions {
  /** Extra rule ids to disable for this assertion. */
  disabledRules?: readonly string[];
}

export async function runAxe(
  target: Element | Document = document.body,
  options: AxeCheckOptions = {},
): Promise<axe.AxeResults> {
  const rules: axe.RuleObject = {};
  for (const rule of [...DEFAULT_DISABLED_RULES, ...(options.disabledRules ?? [])]) {
    rules[rule] = { enabled: false };
  }
  return axe.run(target as axe.ElementContext, { rules });
}

/** Fails with the offending rule ids and target selectors when anything is violated. */
export async function expectNoAxeViolations(
  target: Element | Document = document.body,
  options: AxeCheckOptions = {},
): Promise<void> {
  const results = await runAxe(target, options);
  if (results.violations.length > 0) {
    const summary = results.violations
      .map(
        (violation) =>
          `${violation.id}: ${violation.help} -> ${violation.nodes
            .map((node) => node.target.join(' '))
            .join(', ')}`,
      )
      .join('\n');
    throw new Error(`Expected no accessibility violations, found:\n${summary}`);
  }
}
