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

/**
 * The whole page, not the part that happens to be on screen.
 *
 * A research page is its own scroll container: `.rh-full-page` is `overflow: auto` at the
 * height of the pane, so the document is exactly one viewport tall and `fullPage` captures
 * only the first screenful — the seeded Overview's captures stopped at the first claim
 * health line, with the open questions and the colophon missing from the record. An element
 * screenshot does not help either, because that element's box *is* the visible one.
 *
 * Growing the viewport to the page's own scroll height puts all of it on one screen for the
 * capture, and the viewport is restored afterwards so nothing measured later sees a
 * different layout.
 */
async function captureWholePage(
  page: import('@playwright/test').Page,
  path: string,
): Promise<void> {
  const viewport = page.viewportSize()!;
  const tall = await page
    .locator('.rh-full-page')
    .evaluate((node) => node.scrollHeight - node.clientHeight);
  await page.setViewportSize({
    width: viewport.width,
    height: Math.min(viewport.height + Math.ceil(Math.max(tall, 0)) + 16, 8000),
  });
  await page.screenshot({ path, fullPage: true });
  await page.setViewportSize(viewport);
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
  // The stale object is named by what it is, and so is the evidence that moved under it.
  await expect(
    page.getByText(
      /upstream evidence “dataset · Deep Representations for Encrypted Network Traffic” changed/,
    ),
  ).toBeVisible();
  await expect(page.getByRole('heading', { name: 'Since your last session' })).toBeVisible();
  await expect(page.getByText('accepted methodology decision D0001')).toBeVisible();
  await expect(page.getByText(/changes in the last seven days\./)).toBeVisible();
  await expect(page.getByRole('link', { name: '1 claim is' })).toBeVisible();

  // Whose change each one was, in words inside the sentence: the researcher accepted the
  // Decision, and the disagreement the store attributes to nobody says nothing about who
  // opened it rather than guessing (wave 5J).
  const decided = page
    .locator('.rh-change-list__entry')
    .filter({ hasText: 'accepted methodology decision D0001' });
  await expect(decided).toHaveAttribute('data-by', 'researcher');
  await expect(decided.locator('.rh-change-list__what')).toHaveText(
    /^You accepted methodology decision D0001/,
  );
  const opened = page.locator('.rh-change-list__entry').filter({ hasText: 'was opened' });
  await expect(opened).toHaveCount(1);
  expect(
    await opened.evaluate((node) => node.hasAttribute('data-by')),
    'a conflict opening the record attributes to nobody stays unattributed',
  ).toBe(false);
  // Unattributed is not subjectless. Every other row here begins "You …"; a verb-initial
  // fragment among them reads as an instruction, so the entry with no actor is passive and
  // its subject is the conflict — which says no more about who than the record does.
  await expect(opened.locator('.rh-change-list__what')).toHaveText(
    /^A conflict was opened: the staged F1 differs/,
  );

  // "Look again" says when it last looked, and only announces a read the researcher asked
  // for: an automatic one is quiet text (critique H1).
  const read = page.locator('.rh-web-overview__read');
  await expect(read).toHaveText(/^Read at \d{1,2}:\d{2}/);
  expect(
    await read.evaluate((node) => node.getAttribute('role')),
    'an automatic read announces nothing',
  ).toBeNull();
  await page.locator('.rh-full-page__header').screenshot({
    path: info.outputPath('overview-read-at.png'),
  });
  await page.getByRole('button', { name: 'Look again' }).click();
  await expect(read).toHaveAttribute('role', 'status');
  await expect(read).toHaveText(/^Read at \d{1,2}:\d{2}/);
  // The read the press asked for lands and the page comes back; everything measured below
  // is measured on the page as it stands after it, not on the skeleton in between.
  await expect(page.getByRole('heading', { name: 'Waiting for a decision' })).toBeVisible();

  // Rule 9 of the page's own pattern: a line that names a group, then the items in it
  // indented one space unit under it — the one cue that they belong to that line. Both
  // groups take the same indent, because they are one shape read twice.
  const indents = await page.evaluate(() => {
    const left = (selector: string): number | null => {
      const node = document.querySelector(selector);
      return node instanceof HTMLElement ? node.getBoundingClientRect().left : null;
    };
    return {
      waitingLine: left('.rh-web-attention > li > p'),
      waitingItem: left('.rh-web-attention__items > li'),
      staleLine: left('.rh-web-overview__group > p'),
      staleItem: left('.rh-web-overview__stale > li'),
    };
  });
  expect(Object.values(indents).every((value) => value !== null), 'both groups drew').toBe(true);
  expect(
    indents.staleItem!,
    'a stale object is indented under the line that names its group',
  ).toBeGreaterThan(indents.staleLine!);
  expect(
    indents.staleItem! - indents.staleLine!,
    'both groups indent their items by the same unit',
  ).toBeCloseTo(indents.waitingItem! - indents.waitingLine!, 1);

  // A waiting item leads to the item, not only to the list it is in.
  const item = page.getByRole('link', { name: /metric result · W0001/ });
  await expect(item).toHaveAttribute('href', new RegExp(`^${project.overview_url.replace('/overview', '/review/')}`));

  expect(await bareNumbers(page), 'no number stands on its own').toEqual([]);
  await auditPage(page, 'the overview');
  await captureWholePage(page, info.outputPath('overview.png'));
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
  await captureWholePage(page, info.outputPath('overview-new-project.png'));
  expect(errors).toEqual([]);
});
