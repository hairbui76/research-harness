/**
 * The accessibility gate the browser suite runs, in one place.
 *
 * `withTags(['wcag2a', 'wcag2aa', 'wcag21aa'])` runs only the rules carrying those tags,
 * and the questions a whole document raises — is there exactly one `main`, does the page
 * have an `h1`, do the headings descend in order, does every pane sit in a named region —
 * are answered by rules axe tags `best-practice` instead. They were therefore never run,
 * which is what the roadmap's 2H row means by "axe with contrast, landmark and heading
 * rules on".
 *
 * axe resolves `options.rules[id].enabled` before it consults the tag filter
 * (`ruleShouldRun`), so naming a rule here turns it on without widening the suite to the
 * whole `best-practice` catalogue: those are hundreds of opinions nobody on this project
 * chose, and a gate the team did not choose is a gate the team turns off. The rules below
 * are the ones the roadmap names, and each is a real defect on a cockpit route rather than
 * a stylistic preference.
 *
 * `color-contrast`, `bypass`, `document-title` and `html-has-lang` are already WCAG-tagged
 * and need no entry; they run wherever the context is the whole page. That is the second
 * half of 2H: a spec that scopes axe to one component (`.include('.rh-composer')`) drops
 * every page-level rule *and* every contrast defect outside it, so this module deliberately
 * offers no way to scope the run.
 */
import AxeBuilder from '@axe-core/playwright';
import type { Page } from '@playwright/test';

/** The WCAG tags the suite has always run. */
export const WCAG_TAGS = ['wcag2a', 'wcag2aa', 'wcag21aa'];

/**
 * The page-level rules, on top of the tags.
 *
 * - `region`: every pane's content belongs to a landmark, so a screen-reader user can jump
 *   between the rail, the workspace and the inspector instead of arrowing through them.
 * - `landmark-one-main` and `landmark-no-duplicate-*`: one main surface per route, and one
 *   banner and one contentinfo at most — a second `main` makes "skip to main content" a
 *   coin toss.
 * - `landmark-unique`: two landmarks of the same role need different names.
 * - `page-has-heading-one` and `heading-order`: every destination says which page it is,
 *   and its outline descends without gaps.
 */
export const ROUTE_RULES: Record<string, { enabled: boolean }> = {
  region: { enabled: true },
  'landmark-one-main': { enabled: true },
  'landmark-no-duplicate-main': { enabled: true },
  'landmark-no-duplicate-banner': { enabled: true },
  'landmark-no-duplicate-contentinfo': { enabled: true },
  'landmark-unique': { enabled: true },
  'page-has-heading-one': { enabled: true },
  'heading-order': { enabled: true },
  bypass: { enabled: true },
  'document-title': { enabled: true },
  'html-has-lang': { enabled: true },
  'color-contrast': { enabled: true },
};

/**
 * An axe run over the whole page, with the tags and the page-level rules above.
 *
 * `options` before `withTags`: `AxeBuilder#options` replaces the option object, and
 * `withTags` only sets `runOnly` on it.
 */
export function routeAxe(page: Page): AxeBuilder {
  return new AxeBuilder({ page }).options({ rules: ROUTE_RULES }).withTags(WCAG_TAGS);
}

/**
 * Every violation on the page, as one readable line each.
 *
 * A rule id with the selectors it fired on is what a failing gate has to say for the
 * failure to be actionable; the raw `violations` array prints a page of JSON per node.
 */
export async function axeViolations(page: Page): Promise<string[]> {
  const results = await routeAxe(page).analyze();
  return results.violations.map(
    (violation) =>
      `${violation.id}: ${violation.help} -> ` +
      violation.nodes.map((node) => node.target.join(' ')).join(', '),
  );
}
