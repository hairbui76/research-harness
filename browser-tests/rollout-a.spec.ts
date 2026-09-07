/**
 * Claims, Questions and Conflicts in a real browser, against the real daemon.
 *
 * The Overview proved the pattern; these three are the first pages to follow it. What is
 * asserted here is the part of it that a unit test cannot see: the *reading order* on a
 * rendered page. What needs a researcher is in the first screenful and above any count of
 * what the project holds; nothing on any of the three is a number standing on its own; and
 * on a project with nothing in it yet, every group still teaches what it is for and offers
 * one real next action.
 *
 * `/__test__/rollout-project` builds all of that through the daemon's own services: a Claim
 * asking for more of the scope ladder than its evidence allows, a Question nobody has
 * answered, and two open disagreements, one of them over a staged candidate. So these pages
 * are composed from real state rather than from a fixture.
 */
import { expect, test } from '@playwright/test';
import type { Page } from '@playwright/test';
import { axeViolations } from './axe';

test.beforeEach(async ({ page }, info) => {
  await page.addInitScript((theme) => {
    localStorage.setItem('research-harness:design:appearance', JSON.stringify({ theme }));
  }, info.project.name.endsWith('light') ? 'light' : 'dark');
});

/**
 * Every leaf element inside the page frame whose whole text is a number.
 *
 * A count belongs inside a sentence or on a link that acts on it. An element whose entire
 * content is "12" is the stat tile the brief rules out, however small it is drawn.
 */
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

/** axe, the horizontal-overflow check and the bare-number check, over one rendered page. */
async function auditPage(page: Page, name: string): Promise<void> {
  expect(await axeViolations(page), `${name} must have no accessibility violations`).toEqual([]);
  const fits = await page.evaluate(
    () => document.documentElement.scrollWidth <= window.innerWidth,
  );
  expect(fits, `${name} must not overflow horizontally`).toBeTruthy();
  expect(await bareNumbers(page), `no number on ${name} stands on its own`).toEqual([]);
}

/** The top of the description, and the top of the first count of what the project holds. */
async function readingOrder(page: Page, holdings: RegExp): Promise<[number, number]> {
  const work = (await page.locator('.rh-full-page__description').boundingBox())!;
  const size = (await page.getByText(holdings).first().boundingBox())!;
  return [work.y, size.y];
}

test('the three rolled-out pages lead with what needs a researcher', async ({
  page,
  request,
}, info) => {
  // Seeding ingests, parses, extracts and verifies a paper before any page is opened.
  test.setTimeout(180_000);
  const errors: string[] = [];
  page.on('pageerror', (error) => errors.push(error.message));

  const bootstrap = await request.get('/__test__/bootstrap');
  expect(bootstrap.ok()).toBeTruthy();
  const { nonce } = await bootstrap.json();
  const seeded = await request.post('/__test__/rollout-project', { timeout: 120_000 });
  expect(seeded.ok()).toBeTruthy();
  const project = await seeded.json();

  await page.goto(`/?bootstrap=${encodeURIComponent(nonce)}`);
  await expect(page.getByRole('heading', { name: 'Your research projects' })).toBeVisible();

  // -- Claims: the concern first, the size of the list after it ---------------
  await page.goto(`${project.workspace_url}/claims`);
  await expect(page.getByRole('heading', { level: 1, name: 'Claims' })).toBeVisible();
  await expect(page.locator('.rh-full-page__description')).toHaveText(
    '1 claim asks for more than its evidence allows.',
  );
  await expect(
    page.getByRole('heading', { name: 'Claims their evidence cannot carry' }),
  ).toBeVisible();
  const [claimWork, claimSize] = await readingOrder(page, /This project has registered 1 claim/);
  expect(claimWork, 'the concern is in the first screenful').toBeLessThan(
    page.viewportSize()!.height,
  );
  expect(claimWork, 'the concern is read before the size of the list').toBeLessThan(claimSize);
  await expect(
    page.getByText('Asks for L3 Field generalization; its evidence allows L0 Individual.'),
  ).toBeVisible();
  await auditPage(page, 'the claims');
  await page.screenshot({ path: info.outputPath('claims.png'), fullPage: true });

  // -- Questions: still open first, answered after -----------------------------
  await page.goto(`${project.workspace_url}/questions`);
  await expect(page.getByRole('heading', { level: 1, name: 'Questions' })).toBeVisible();
  await expect(page.locator('.rh-full-page__description')).toHaveText(
    '1 question is still open.',
  );
  await expect(page.getByText('1 question is still open', { exact: true })).toBeVisible();
  await expect(page.getByText(/no capture in the corpus re-encrypts a flow/)).toBeVisible();
  // The group's line already says every row under it is open, so no row repeats it.
  await expect(page.getByText('Open', { exact: true })).toHaveCount(0);
  // The claims that bear on a question are named by what they assert, not only by id.
  await expect(
    page.getByRole('link', {
      name: 'C0001 Byte-level tokenization improves recall on encrypted traffic',
    }),
  ).toHaveAttribute('href', `${project.workspace_url}/claims/C0001`);
  const open = (await page.getByRole('heading', { name: 'Still open' }).boundingBox())!;
  const answered = (await page.getByRole('heading', { name: 'Answered' }).boundingBox())!;
  expect(open.y, 'what is still open is read before what has been answered').toBeLessThan(
    answered.y,
  );
  await auditPage(page, 'the questions');
  await page.screenshot({ path: info.outputPath('questions.png'), fullPage: true });

  // -- Conflicts: grouped by kind, each pointed where it is decided ------------
  await page.goto(`${project.workspace_url}/conflicts`);
  await expect(page.getByRole('heading', { level: 1, name: 'Conflicts' })).toBeVisible();
  await expect(page.locator('.rh-full-page__description')).toHaveText(
    '2 conflicts are open. Every side is kept, and none of them is preferred until you decide.',
  );
  await expect(page.getByText('Candidate against accepted state')).toBeVisible();
  await expect(page.getByText('Provider against provider')).toBeVisible();
  // The subject is named by what it is: the Claim's own statement, and the words the
  // review queue calls the staged candidate by. The id lives in the route and nowhere else.
  await expect(
    page.getByRole('link', {
      name: 'Byte-level tokenization improves recall on encrypted traffic',
    }),
  ).toHaveAttribute('href', `${project.workspace_url}/claims/C0001`);
  await expect(page.getByRole('link', { name: 'metric result · W0001' })).toHaveAttribute(
    'href',
    new RegExp(`^${project.workspace_url}/review/cand_`),
  );
  await expect(page.getByText(/cand_[0-9a-f]{16}/)).toHaveCount(0);
  await auditPage(page, 'the conflicts');
  await page.screenshot({ path: info.outputPath('conflicts.png'), fullPage: true });

  expect(errors).toEqual([]);
});

test('every group of a new project teaches what it is for and offers one next action', async ({
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
  await page.getByLabel('Project name', { exact: true }).fill(`New rollout ${info.project.name}`);
  await page.getByRole('button', { name: 'Choose parent folder' }).click();
  await page.getByLabel('Parent folder path').fill(parent);
  const created = page.waitForResponse(
    (r) => r.url().endsWith('/api/projects/create') && r.request().method() === 'POST',
  );
  await page.getByRole('button', { name: 'Create project', exact: true }).click();
  expect((await created).ok()).toBeTruthy();

  await page.waitForURL(/\/projects\/[^/?#]+/);
  const workspace = new URL(page.url()).pathname.replace(/\/$/, '');

  /** Each page, the sentence its empty state states, and the one step it offers. */
  const EMPTY: { path: string; description: string; title: string; action: string }[] = [
    {
      path: 'claims',
      description: 'This project has registered no claims yet.',
      title: 'No claims registered yet',
      action: 'Open the conversation to promote a claim',
    },
    {
      path: 'questions',
      description: 'This project has registered no questions yet.',
      title: 'No questions yet',
      action: 'Open the conversation to promote a question',
    },
    {
      path: 'conflicts',
      description: 'Nothing in this project is in dispute.',
      title: 'No open conflicts',
      action: 'Open the review inbox',
    },
  ];

  for (const entry of EMPTY) {
    await page.goto(`${workspace}/${entry.path}`);
    await expect(page.locator('.rh-full-page__description')).toHaveText(entry.description);
    await expect(page.getByText(entry.title, { exact: true })).toBeVisible();
    await expect(
      page.getByRole('link', { name: entry.action }),
      `the empty ${entry.path} page must offer "${entry.action}"`,
    ).toBeVisible();
    await auditPage(page, `the empty ${entry.path} page`);
    await page.screenshot({ path: info.outputPath(`${entry.path}-new-project.png`), fullPage: true });
  }

  expect(errors).toEqual([]);
});
