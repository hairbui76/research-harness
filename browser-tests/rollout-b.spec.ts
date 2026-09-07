/**
 * Stale, Taxonomy and Synthesis in a real browser, against the real daemon.
 *
 * `/__test__/research-pages` builds a project through the daemon's own services until all
 * three pages have something to report: a classification with a term no Decision approves,
 * a matrix that declares a reading nobody has recorded, and real decay under both, produced
 * by running the daemon's invalidation hook over the Decision that approved the taxonomy.
 * So what is asserted below is three pages composed from real state, not from a fixture.
 *
 * The proof each page has to keep is the Overview's: the first screenful names the work
 * before any count of what the project holds, no number stands on its own, and — for the
 * Stale page — the decay is reported in the same words the Overview's "Gone stale" group
 * uses, because two accounts of one fact is one account too many.
 */
import { expect, test } from '@playwright/test';
import type { Page } from '@playwright/test';
import { axeViolations } from './axe';

test.beforeEach(async ({ page }, info) => {
  await page.addInitScript((theme) => {
    localStorage.setItem('research-harness:design:appearance', JSON.stringify({ theme }));
  }, info.project.name.endsWith('light') ? 'light' : 'dark');
});

/** Every leaf element inside the page frame whose whole text is a number. */
async function bareNumbers(page: Page): Promise<string[]> {
  return page.evaluate(() => {
    const found: string[] = [];
    for (const node of Array.from(document.querySelectorAll('.rh-full-page *'))) {
      if (!(node instanceof HTMLElement) || node.children.length > 0) continue;
      if ((node.textContent ?? '').trim().match(/^\d+([.,]\d+)?%?$/)) found.push(node.outerHTML);
    }
    return found;
  });
}

async function auditPage(page: Page, name: string): Promise<void> {
  expect(await axeViolations(page), `${name} must have no accessibility violations`).toEqual([]);
  const fits = await page.evaluate(
    () => document.documentElement.scrollWidth <= window.innerWidth,
  );
  expect(fits, `${name} must not overflow horizontally`).toBeTruthy();
}

/**
 * The work is named in the first screenful, and before any count of what the project holds.
 *
 * The page's description is the daemon's own sentence about what needs a researcher here;
 * the first panel is the group that sentence is about. Both are above the fold, and the
 * page's own inventory — the classification, the matrices, the objects — comes after.
 */
async function leadsWithTheWork(
  page: Page,
  name: string,
  work: string | null,
  holdings: string,
): Promise<void> {
  const description = page.locator('.rh-full-page__description');
  await expect(description).toBeVisible();
  const lead = (await description.boundingBox())!;
  expect(lead.y, `${name} names the work in the first screenful`).toBeLessThan(
    page.viewportSize()!.height,
  );
  const inventory = (await page.getByRole('heading', { level: 2, name: holdings }).boundingBox())!;
  expect(lead.y, `${name} names the work before what the project holds`).toBeLessThan(inventory.y);
  if (work !== null) {
    const panel = (await page.getByRole('heading', { level: 2, name: work }).boundingBox())!;
    expect(panel.y, `${name} opens with the group the work is in`).toBeLessThan(
      page.viewportSize()!.height,
    );
    expect(panel.y, `${name} reads the work before what the project holds`).toBeLessThan(
      inventory.y,
    );
  }
  expect(await bareNumbers(page), `no number stands on its own on ${name}`).toEqual([]);
}

test('the three rolled-out pages lead with the work the daemon composed', async ({
  page,
  request,
}, info) => {
  // Seeding ingests and parses a paper before the pages are opened.
  test.setTimeout(120_000);
  const errors: string[] = [];
  page.on('pageerror', (error) => errors.push(error.message));

  const bootstrap = await request.get('/__test__/bootstrap');
  expect(bootstrap.ok()).toBeTruthy();
  const { nonce } = await bootstrap.json();
  const seeded = await request.post('/__test__/research-pages', { timeout: 90_000 });
  expect(seeded.ok()).toBeTruthy();
  const project = await seeded.json();

  await page.goto(`/?bootstrap=${encodeURIComponent(nonce)}`);
  await expect(page.getByRole('heading', { name: 'Your research projects' })).toBeVisible();

  // -- Stale: what went out of date, in the Overview's own words ------------
  await page.goto(`${project.workspace_url}/overview`);
  await expect(page.getByRole('heading', { name: 'Gone stale' })).toBeVisible();
  const onOverview = (await page
    .locator('.rh-web-overview__stale > li')
    .first()
    .innerText()).replace(/\s+/g, ' ').trim();
  expect(onOverview, 'the Overview reports the decay with a reason').toContain('—');

  await page.goto(`${project.workspace_url}/stale`);
  await expect(page.getByRole('heading', { level: 1, name: 'Stale objects' })).toBeVisible();
  await expect(page.locator('.rh-full-page__description')).toHaveText(/went stale because/);
  await leadsWithTheWork(page, 'the stale page', null, 'Synthesis matrices');
  const onStale = (await page
    .locator('.rh-web-stale__items > li')
    .first()
    .innerText()).replace(/\s+/g, ' ').trim();
  expect(onStale, 'one decay is reported in one set of words on both pages').toEqual(onOverview);
  await auditPage(page, 'the stale page');
  await page.screenshot({ path: info.outputPath('stale.png'), fullPage: true });

  // -- Taxonomy: the terms no accepted Decision stands behind ---------------
  await page.goto(`${project.workspace_url}/taxonomy`);
  await expect(page.getByRole('heading', { level: 1, name: 'Taxonomy' })).toBeVisible();
  await expect(page.locator('.rh-full-page__description')).toHaveText(
    /no accepted Decision behind/,
  );
  await expect(page.getByRole('heading', { level: 2, name: 'Waiting for a Decision' })).toBeVisible();
  await expect(page.getByText('padded_fixed · traffic-shape')).toBeVisible();
  await expect(page.getByText('— no Decision approves it yet')).toBeVisible();
  // The classification stays a table, and it is the tree the daemon walked.
  await expect(page.getByRole('columnheader', { name: 'Parent' })).toHaveCount(0);
  await expect(page.locator('.rh-web-taxonomy__term[data-depth="1"]')).toHaveCount(1);
  await leadsWithTheWork(page, 'the taxonomy page', 'Waiting for a Decision', 'traffic-shape');
  await auditPage(page, 'the taxonomy page');
  await page.screenshot({ path: info.outputPath('taxonomy.png'), fullPage: true });

  // -- Synthesis: what the matrix cannot say yet ----------------------------
  await page.goto(`${project.workspace_url}/synthesis`);
  await expect(page.getByRole('heading', { level: 1, name: 'Synthesis' })).toBeVisible();
  await expect(page.locator('.rh-full-page__description')).toHaveText(/not been recorded yet/);
  await expect(
    page.getByRole('heading', { level: 2, name: 'What these matrices cannot say yet' }),
  ).toBeVisible();
  await expect(page.getByText('— no work in this matrix has been read for it yet')).toBeVisible();
  await expect(page.getByText(/never means the work lacks the property/)).toBeVisible();
  // The matrix itself stays a table, reached through the compare form it has always had.
  await page.getByLabel('Field').fill('tokenization');
  await page.getByRole('button', { name: 'Compare' }).click();
  await expect(page.getByRole('columnheader', { name: 'Work' })).toBeVisible();
  await leadsWithTheWork(
    page,
    'the synthesis page',
    'What these matrices cannot say yet',
    'Traffic shape',
  );
  await auditPage(page, 'the synthesis page');
  await page.screenshot({ path: info.outputPath('synthesis.png'), fullPage: true });

  expect(errors).toEqual([]);
});

test('each rolled-out page teaches its empty groups on a project with nothing in it', async ({
  page,
  request,
}, info) => {
  test.setTimeout(120_000);
  const errors: string[] = [];
  page.on('pageerror', (error) => errors.push(error.message));

  const response = await request.get('/__test__/bootstrap');
  expect(response.ok()).toBeTruthy();
  const { nonce, parent } = await response.json();
  await page.goto(`/?bootstrap=${encodeURIComponent(nonce)}`);
  await expect(page.getByRole('heading', { name: 'Your research projects' })).toBeVisible();

  await page.getByRole('button', { name: 'New project', exact: true }).click();
  await page.getByLabel('Project name', { exact: true }).fill(`Rollout B ${info.project.name}`);
  await page.getByRole('button', { name: 'Choose parent folder' }).click();
  await page.getByLabel('Parent folder path').fill(parent);
  const created = page.waitForResponse(
    (r) => r.url().endsWith('/api/projects/create') && r.request().method() === 'POST',
  );
  await page.getByRole('button', { name: 'Create project', exact: true }).click();
  expect((await created).ok()).toBeTruthy();

  await page.waitForURL(/\/projects\/[^/?#]+/);
  const workspace = new URL(page.url()).pathname.replace(/\/$/, '');

  for (const [path, state, action] of [
    ['stale', 'Nothing is stale', 'Open the corpus this project rests on'],
    ['taxonomy', 'No taxonomy has been approved yet', 'Open the conversation to propose a term'],
    ['synthesis', 'No synthesis matrix has been built yet', 'See the works a matrix would read'],
  ]) {
    await page.goto(`${workspace}/${path}`);
    await expect(page.getByRole('heading', { level: 1 })).toBeVisible();
    await expect(page.getByText(state!, { exact: true })).toBeVisible();
    await expect(
      page.getByRole('link', { name: action! }),
      `the empty state on ${path} must offer "${action}"`,
    ).toBeVisible();
    expect(await bareNumbers(page), `no number stands on its own on ${path}`).toEqual([]);
    await auditPage(page, `the empty ${path} page`);
    await page.screenshot({ path: info.outputPath(`${path}-new-project.png`), fullPage: true });
  }

  expect(errors).toEqual([]);
});
