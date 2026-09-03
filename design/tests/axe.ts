import axe from 'axe-core';

/**
 * Shared axe-core harness for the Design System tests.
 *
 * Rules that need a layout engine or a whole document are disabled: jsdom computes no
 * geometry, so `color-contrast` cannot run there (contrast is verified separately against
 * the token values), and page-level landmark rules do not apply to a component fragment.
 */
const DEFAULT_DISABLED_RULES = [
  'color-contrast',
  'region',
  'page-has-heading-one',
  'landmark-one-main',
  'html-has-lang',
  'document-title',
  'bypass',
];

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
