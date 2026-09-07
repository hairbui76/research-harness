/**
 * The Overview in a real browser, against the real daemon.
 *
 * `/__test__/overview-project` builds a project through the daemon's own services until
 * every group on this page has something to say: candidates in the queue, an open conflict,
 * a stale Claim, an accepted Decision, and the event-log entries all of those wrote. So what
 * is asserted below is a page composed from real state, not from a fixture.
 *
 * The proof this page has to keep is its reading order. A researcher opening a project sees
 * what is waiting before any count of what the project holds; nothing on it is a number on
 * its own; and every group that is empty still teaches what it is for and offers one real
 * next action. That is the pattern the rest of the research pages follow.
 */
import { expect, test } from '@playwright/test';
import { axeViolations } from './axe';

test.beforeEach(async ({ page }, info) => {
  await page.addInitScript((theme) => {
    localStorage.setItem('research-harness:design:appearance', JSON.stringify({ theme }));
  }, info.project.name.endsWith('light') ? 'light' : 'dark');
});

/** Every leaf element inside the page frame whose whole text is a number. */
async function bareNumbers(page: import('@playwright/test').Page): Promise<string[]> {
  return page.evaluate(() => {
    const found: string[] = [];
    for (const node of Array.from(document.querySelectorAll('.rh-full-page *'))) {
      if (!(node instanceof HTMLElement) || node.children.length > 0) continue;
      if ((node.textContent ?? '').trim().match(/^\d+([.,]\d+)?%?$/)) found.push(node.outerHTML);
    }
    return found;
  });
}

async function auditPage(page: import('@playwright/test').Page, name: string): Promise<void> {
  expect(await axeViolations(page), `${name} must have no accessibility violations`).toEqual([]);
  const fits = await page.evaluate(
    () => document.documentElement.scrollWidth <= window.innerWidth,
  );
  expect(fits, `${name} must not overflow horizontally`).toBeTruthy();
}

test('the overview leads with what is waiting, and states what the project holds last', async ({
  page,
  request,
}, info) => {
  // Seeding ingests, parses, extracts and verifies a paper before the page is opened.
  test.setTimeout(120_000);
  const errors: string[] = [];
  page.on('pageerror', (error) => errors.push(error.message));

  const bootstrap = await request.get('/__test__/bootstrap');
  expect(bootstrap.ok()).toBeTruthy();
  const { nonce } = await bootstrap.json();
  const seeded = await request.post('/__test__/overview-project', { timeout: 90_000 });
  expect(seeded.ok()).toBeTruthy();
  const project = await seeded.json();

  await page.goto(`/?bootstrap=${encodeURIComponent(nonce)}`);
  await expect(page.getByRole('heading', { name: 'Your research projects' })).toBeVisible();
  await page.goto(project.overview_url);
  await expect(page.getByRole('heading', { name: project.name, level: 1 })).toBeVisible();

  // The daemon's own sentence about what needs a researcher, in the page's description.
  const waiting = page.locator('.rh-full-page__description');
  await expect(waiting).toHaveText(/need a researcher\./);
  await expect(page.getByRole('heading', { name: 'Waiting for a decision' })).toBeVisible();

  // What the project holds comes after it, and never before.
  const holds = page.locator('.rh-web-overview__holdings');
  const waitingBox = (await waiting.boundingBox())!;
  const holdsBox = (await holds.boundingBox())!;
  expect(waitingBox.y, 'what is waiting is in the first screenful').toBeLessThan(
    page.viewportSize()!.height,
  );
  expect(
    waitingBox.y,
    'what is waiting is read before what the project holds',
  ).toBeLessThan(holdsBox.y);

  // Every group has something to say, and each says it in words.
  await expect(page.getByRole('link', { name: '2 review items' })).toBeVisible();
  await expect(page.getByRole('heading', { name: 'Gone stale' })).toBeVisible();
  await expect(page.getByText(/upstream E0001 changed/)).toBeVisible();
  await expect(page.getByRole('heading', { name: 'Since your last session' })).toBeVisible();
  await expect(page.getByText('accepted methodology decision D0001')).toBeVisible();
  await expect(page.getByText(/changes in the last seven days\./)).toBeVisible();
  await expect(page.getByRole('link', { name: '1 claim is' })).toBeVisible();

  // A waiting item leads to the item, not only to the list it is in.
  const item = page.getByRole('link', { name: /metric result · W0001/ });
  await expect(item).toHaveAttribute('href', new RegExp(`^${project.overview_url.replace('/overview', '/review/')}`));

  expect(await bareNumbers(page), 'no number stands on its own').toEqual([]);
  await auditPage(page, 'the overview');
  await page.screenshot({ path: info.outputPath('overview.png'), fullPage: true });
  expect(errors).toEqual([]);
});

test('every group of a new project teaches what it is for and offers one next action', async ({
  page,
  request,
}, info) => {
  const errors: string[] = [];
  page.on('pageerror', (error) => errors.push(error.message));

  const response = await request.get('/__test__/bootstrap');
  expect(response.ok()).toBeTruthy();
  const { nonce, parent } = await response.json();
  await page.goto(`/?bootstrap=${encodeURIComponent(nonce)}`);
  await expect(page.getByRole('heading', { name: 'Your research projects' })).toBeVisible();

  await page.getByRole('button', { name: 'New project', exact: true }).click();
  await page.getByLabel('Project name', { exact: true }).fill(`New overview ${info.project.name}`);
  await page.getByRole('button', { name: 'Choose parent folder' }).click();
  await page.getByLabel('Parent folder path').fill(parent);
  const created = page.waitForResponse(
    (r) => r.url().endsWith('/api/projects/create') && r.request().method() === 'POST',
  );
  await page.getByRole('button', { name: 'Create project', exact: true }).click();
  expect((await created).ok()).toBeTruthy();

  await page.waitForURL(/\/projects\/[^/?#]+/);
  const workspace = new URL(page.url()).pathname.replace(/\/$/, '');
  await page.goto(`${workspace}/overview`);

  await expect(page.getByText('Nothing needs a researcher right now.')).toBeVisible();
  for (const [group, action] of [
    ['Nothing is waiting for a decision', 'Open the review inbox'],
    ['Nothing is stale', 'Open the corpus this project rests on'],
    [
      'No research activity has been recorded in this project yet.',
      'Open the conversation to start the next piece of work',
    ],
    ['No claims registered yet', 'Open the conversation to promote a claim'],
    ['No open questions', 'Open the conversation to promote a question'],
  ]) {
    await expect(page.getByText(group!, { exact: true })).toBeVisible();
    await expect(
      page.getByRole('link', { name: action! }),
      `the empty group "${group}" must offer "${action}"`,
    ).toBeVisible();
  }

  expect(await bareNumbers(page), 'no number stands on its own').toEqual([]);
  await auditPage(page, 'the overview of a new project');
  await page.screenshot({ path: info.outputPath('overview-new-project.png'), fullPage: true });
  expect(errors).toEqual([]);
});
