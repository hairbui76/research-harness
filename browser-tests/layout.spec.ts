/**
 * Whether the cockpit's layout checks that its own content fits.
 *
 * Three things this suite measures rather than assumes, because none of them can be seen
 * without a browser: prose holds a reading measure at a width no unit test ever renders;
 * six inspector tabs are all reachable inside a pane about a third as wide as they are; and
 * the two places that offer project lifecycle actions offer the same ones, in the same
 * order, under the same words.
 *
 * Both Playwright projects run all of it, and the measure test resizes to 1920x1080 inside
 * the test, because that is the width the critique measured 232-character lines at.
 */
import { expect, test } from '@playwright/test';
import type { APIRequestContext, Locator, Page, TestInfo } from '@playwright/test';
import AxeBuilder from '@axe-core/playwright';

test.beforeEach(async ({ page }, info) => {
  await page.addInitScript((theme) => {
    localStorage.setItem('research-harness:design:appearance', JSON.stringify({ theme }));
  }, info.project.name.endsWith('light') ? 'light' : 'dark');
});

/** A registered project, opened at its own URL. Every test here needs one of its own. */
async function openWorkspace(
  page: Page,
  request: APIRequestContext,
  info: TestInfo,
  name: string,
): Promise<string> {
  const response = await request.get('/__test__/bootstrap');
  expect(response.ok()).toBeTruthy();
  const { nonce, parent } = await response.json();
  await page.goto(`/?bootstrap=${encodeURIComponent(nonce)}`);
  await expect(page.getByRole('heading', { name: 'Your research projects' })).toBeVisible();

  await page.getByRole('button', { name: 'New project', exact: true }).click();
  await page.getByLabel('Project name', { exact: true }).fill(`${name} ${info.project.name}`);
  await page.getByRole('button', { name: 'Choose parent folder' }).click();
  await page.getByLabel('Parent folder path').fill(parent);
  const created = page.waitForResponse(
    (r) => r.url().endsWith('/api/projects/create') && r.request().method() === 'POST',
  );
  await page.getByRole('button', { name: 'Create project', exact: true }).click();
  expect((await created).ok()).toBeTruthy();

  await page.waitForURL(/\/projects\/[^/?#]+/);
  // The URL changes before the registry has the new project, and until it does the shell
  // still renders Project Home under a project URL. Waiting for the workspace's own main
  // landmark is what makes everything after this point about the workspace.
  await expect(page.getByRole('main', { name: 'Research workspace' })).toBeVisible();
  return new URL(page.url()).pathname.replace(/\/$/, '');
}

/**
 * How many characters wide a run of text actually is.
 *
 * `ch` is the width of a zero in the element's own font, so a probe that inherits the
 * element's typography converts its measured width into the unit the craft floor is
 * written in. Dividing pixels by the font size would answer in `em` instead, which is a
 * different and looser number.
 */
async function measureInCharacters(page: Page, selector: string): Promise<number> {
  return page.evaluate((css) => {
    const element = document.querySelector(css);
    if (!(element instanceof HTMLElement)) throw new Error(`no element matched ${css}`);
    const probe = document.createElement('span');
    probe.style.display = 'inline-block';
    probe.style.inlineSize = '1ch';
    probe.style.position = 'absolute';
    probe.style.visibility = 'hidden';
    element.appendChild(probe);
    const oneCharacter = probe.getBoundingClientRect().width;
    probe.remove();
    return element.getBoundingClientRect().width / oneCharacter;
  }, selector);
}

/** The labels of the menu a "Project actions" trigger opens, then closed again. */
async function projectActionLabels(page: Page, trigger: Locator): Promise<string[]> {
  await trigger.click();
  const items = page.getByRole('menuitem');
  await expect(items.first()).toBeVisible();
  const labels = await items.allInnerTexts();
  await page.keyboard.press('Escape');
  await expect(items.first()).toBeHidden();
  return labels.map((label) => label.trim());
}

/** Below the shell's breakpoint the rail is a drawer, so it has to be opened first. */
async function openRail(page: Page): Promise<void> {
  const opener = page.getByRole('button', { name: 'Project navigation', exact: true });
  if (await opener.isVisible()) await opener.click();
}

test('prose holds a reading measure on a 1920px screen while the page does not overflow', async ({
  page,
  request,
}, info) => {
  test.setTimeout(120_000);
  const errors: string[] = [];
  page.on('pageerror', (error) => errors.push(error.message));

  const workspace = await openWorkspace(page, request, info, 'Measure study');
  await page.setViewportSize({ width: 1920, height: 1080 });

  await page.goto(`${workspace}/corpus`);
  await expect(page.getByRole('heading', { level: 1, name: 'Corpus' })).toBeVisible();

  const description = await measureInCharacters(page, '.rh-full-page__description');
  // A cap that produced nothing would also be under 75; the floor says it is real text.
  expect(description, 'the page description must be a measured run of text').toBeGreaterThan(20);
  expect(
    description,
    `the page description ran ${description.toFixed(0)} characters at 1920px`,
  ).toBeLessThanOrEqual(75);

  // The table beside it is scanned, not read, and keeps the width the page gives it.
  const wide = await page.evaluate(() => {
    const content = document.querySelector('.rh-full-page__content');
    const prose = document.querySelector('.rh-full-page__description');
    if (!(content instanceof HTMLElement) || !(prose instanceof HTMLElement)) return null;
    return {
      content: content.getBoundingClientRect().width,
      prose: prose.getBoundingClientRect().width,
    };
  });
  expect(wide).not.toBeNull();
  expect(wide!.prose, 'prose must be capped well inside the page body').toBeLessThan(
    wide!.content * 0.8,
  );

  const results = await new AxeBuilder({ page })
    .withTags(['wcag2a', 'wcag2aa', 'wcag21aa'])
    .analyze();
  expect(results.violations).toEqual([]);

  const fits = await page.evaluate(
    () => document.documentElement.scrollWidth <= window.innerWidth,
  );
  expect(fits, 'a 1920px window must not overflow horizontally').toBeTruthy();

  await page.screenshot({ path: info.outputPath('measure-1920.png'), fullPage: true });
  expect(errors).toEqual([]);
});

test('every inspector tab is reachable from the keyboard at both widths', async ({
  page,
  request,
}, info) => {
  test.setTimeout(120_000);
  const errors: string[] = [];
  page.on('pageerror', (error) => errors.push(error.message));

  await openWorkspace(page, request, info, 'Inspector study');

  for (const width of [1920, 768]) {
    await page.setViewportSize({ width, height: 1024 });

    // "Show" exists only while the inspector is closed, so its presence is the question.
    const show = page.getByRole('button', { name: 'Show the research inspector', exact: true });
    if ((await show.count()) > 0) await show.first().click();

    const inspector = page.getByRole('region', { name: 'Research inspector' });
    await expect(inspector).toBeVisible();
    const tabs = inspector.getByRole('tab');
    await expect(tabs, `six tabs at ${width}px`).toHaveCount(6);

    await tabs.first().focus();
    for (let index = 0; index < 6; index += 1) {
      const tab = tabs.nth(index);
      await expect(tab, `tab ${index} must hold focus at ${width}px`).toBeFocused();
      // Clipped by the strip counts as out of the viewport, which is the point.
      await expect(tab, `tab ${index} must be in view at ${width}px`).toBeInViewport();
      if (index < 5) await page.keyboard.press('ArrowRight');
    }

    const results = await new AxeBuilder({ page })
      .withTags(['wcag2a', 'wcag2aa', 'wcag21aa'])
      .analyze();
    expect(results.violations, `axe at ${width}px`).toEqual([]);

    const fits = await page.evaluate(
      () => document.documentElement.scrollWidth <= window.innerWidth,
    );
    expect(fits, `the conversation must not overflow sideways at ${width}px`).toBeTruthy();

    await page.screenshot({ path: info.outputPath(`inspector-${width}.png`), fullPage: true });
  }

  expect(errors).toEqual([]);
});

test('the rail and Project Home offer the same project actions in the same words', async ({
  page,
  request,
}, info) => {
  test.setTimeout(120_000);
  const errors: string[] = [];
  page.on('pageerror', (error) => errors.push(error.message));

  await openWorkspace(page, request, info, 'Vocabulary study');
  await openRail(page);
  const fromRail = await projectActionLabels(
    page,
    page.getByRole('button', { name: 'Project actions', exact: true }),
  );
  expect(fromRail).toEqual([
    'Show in file manager',
    'Locate folder',
    'Rename',
    'Forget project',
  ]);
  await page.screenshot({ path: info.outputPath('rail-actions.png'), fullPage: true });

  // Project Home is reached the way a researcher reaches it. A fresh load of `/` would
  // reopen the last project instead (spec §4.2), which is the point of that rule.
  await page.getByRole('button', { name: /^Project: .* Switch project$/ }).click();
  await page.getByRole('menuitem', { name: 'All projects', exact: true }).click();
  await expect(page.getByRole('heading', { name: 'Your research projects' })).toBeVisible();

  const list = page.getByRole('list', { name: 'Registered projects' });
  await expect(list).toBeVisible();
  const row = list.getByRole('listitem').first();
  // One visible act per row — the one that opens the workspace — and the rest in the menu.
  await expect(row.getByRole('button')).toHaveText(['Open', 'Project actions']);

  const fromHome = await projectActionLabels(
    page,
    row.getByRole('button', { name: 'Project actions', exact: true }),
  );
  expect(fromHome, 'Project Home must offer the rail’s actions verbatim').toEqual(fromRail);

  const results = await new AxeBuilder({ page })
    .withTags(['wcag2a', 'wcag2aa', 'wcag21aa'])
    .analyze();
  expect(results.violations).toEqual([]);

  await page.screenshot({ path: info.outputPath('project-home-actions.png'), fullPage: true });
  expect(errors).toEqual([]);
});
