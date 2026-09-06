/**
 * The eight research pages, in a browser, on a project that has nothing in it yet.
 *
 * A brand-new project is the state every one of these pages is in the first time anybody
 * opens it, and it used to be the state they handled worst: the page returned its empty
 * state instead of itself, so there was no `h1` for the shell's skip link to land on and
 * nothing on screen said what the page was for or what to do next.
 *
 * So each page is asserted for four things at both widths the suite runs: the heading is
 * there, the empty state offers a real next step as a link, axe finds nothing, and the
 * layout does not overflow sideways.
 */
import { expect, test } from '@playwright/test';
import AxeBuilder from '@axe-core/playwright';

test.beforeEach(async ({ page }, info) => {
  await page.addInitScript((theme) => {
    localStorage.setItem('research-harness:design:appearance', JSON.stringify({ theme }));
  }, info.project.name.endsWith('light') ? 'light' : 'dark');
});

/**
 * Each page, and the one thing a researcher can do from it while it is empty.
 *
 * `heading` is null for the Overview alone: its `h1` is the project's own name, which the
 * daemon reports rather than this test choosing it.
 */
const PAGES: { path: string; heading: string | null; action: string }[] = [
  { path: 'overview', heading: null, action: 'Open the conversation to promote a claim' },
  { path: 'corpus', heading: 'Corpus', action: 'Open the conversation to attach a source' },
  { path: 'claims', heading: 'Claims', action: 'Open the conversation to promote a claim' },
  { path: 'questions', heading: 'Questions', action: 'Open the conversation to promote a question' },
  { path: 'conflicts', heading: 'Conflicts', action: 'Open the review inbox' },
  { path: 'stale', heading: 'Stale objects', action: 'See what else needs attention' },
  { path: 'synthesis', heading: 'Synthesis', action: 'See the works a matrix would read' },
  { path: 'taxonomy', heading: 'Taxonomy', action: 'Open the conversation to propose a term' },
];

test('every research page keeps its frame and teaches its empty state on a new project', async ({
  page,
  request,
}, info) => {
  // Eight pages, each with an axe pass and a screenshot, is more than one default timeout.
  test.setTimeout(180_000);
  const errors: string[] = [];
  page.on('pageerror', (error) => errors.push(error.message));

  const response = await request.get('/__test__/bootstrap');
  expect(response.ok()).toBeTruthy();
  const { nonce, parent } = await response.json();
  await page.goto(`/?bootstrap=${encodeURIComponent(nonce)}`);
  await expect(page.getByRole('heading', { name: 'Your research projects' })).toBeVisible();

  await page.getByRole('button', { name: 'New project', exact: true }).click();
  await page.getByLabel('Project name', { exact: true }).fill(`Empty study ${info.project.name}`);
  await page.getByRole('button', { name: 'Choose parent folder' }).click();
  await page.getByLabel('Parent folder path').fill(parent);
  const created = page.waitForResponse(
    (r) => r.url().endsWith('/api/projects/create') && r.request().method() === 'POST',
  );
  await page.getByRole('button', { name: 'Create project', exact: true }).click();
  expect((await created).ok()).toBeTruthy();

  await page.waitForURL(/\/projects\/[^/?#]+/);
  const workspace = new URL(page.url()).pathname.replace(/\/$/, '');

  for (const entry of PAGES) {
    await page.goto(`${workspace}/${entry.path}`);

    // The frame: whatever the body is doing, the page says which page it is.
    const heading = page.getByRole('heading', { level: 1 });
    await expect(heading, `${entry.path} must have a level-1 heading`).toBeVisible();
    if (entry.heading !== null) await expect(heading).toHaveText(entry.heading);

    // The empty state: one real next step, reachable as a link.
    await expect(
      page.getByRole('link', { name: entry.action }),
      `${entry.path} must offer "${entry.action}"`,
    ).toBeVisible();

    const results = await new AxeBuilder({ page })
      .withTags(['wcag2a', 'wcag2aa', 'wcag21aa'])
      .analyze();
    expect(results.violations, `${entry.path} must have no accessibility violations`).toEqual([]);

    const fits = await page.evaluate(
      () => document.documentElement.scrollWidth <= window.innerWidth,
    );
    expect(fits, `${entry.path} must not overflow horizontally`).toBeTruthy();

    await page.screenshot({ path: info.outputPath(`${entry.path}.png`), fullPage: true });
  }

  expect(errors).toEqual([]);
});
